import SwiftUI
import CoreLocation

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.horizontalSizeClass) private var sizeClass

    var body: some View {
        Group {
            if let error = model.loadError {
                ContentUnavailableView("Couldn't open the list", systemImage: "exclamationmark.triangle", description: Text(error))
            } else if !model.isLoaded {
                ProgressView("Loading Texas restaurants…").tint(Theme.green).foregroundStyle(Theme.muted)
            } else if sizeClass == .regular {
                SplitRoot()
            } else {
                TabRoot()
            }
        }
        .background(Theme.surface)
    }
}

/// iPhone: tabs, each with its own navigation stack.
struct TabRoot: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        TabView(selection: $model.tab) {
            NavigationStack(path: $model.guidesPath) {
                HomeView()
                    .navigationDestination(for: AppModel.Route.self) { route in
                        switch route {
                        case .guide(let g): GuideListView(guide: g)
                        case .place(let p): PlaceDetailView(place: p)
                        }
                    }
            }
                .tabItem { Label("Guides", systemImage: "list.bullet.rectangle") }.tag(AppModel.Tab.guides)
            NavigationStack { MapScreen() }
                .tabItem { Label("Map", systemImage: "map") }.tag(AppModel.Tab.map)
            NavigationStack { SavedView() }
                .tabItem { Label("Saved", systemImage: "heart") }.tag(AppModel.Tab.saved)
            NavigationStack { AboutView() }
                .tabItem { Label("About", systemImage: "info.circle") }.tag(AppModel.Tab.about)
        }
        .onAppear(perform: restore)
        .onChange(of: model.guidesPath) { model.followPath() }
    }

    /// Coming from the iPad layout (Split View, Stage Manager): reopen the list and place that were open there.
    private func restore() {
        switch model.tab {
        case .guides:
            let path = model.compactPath
            if model.guidesPath != path { model.guidesPath = path }
        case .map, .saved:
            model.handoffPlace = model.selectedPlace
        case .about:
            break
        }
    }
}

/// iPad: guides in the sidebar, the list in the middle, the place on the right.
struct SplitRoot: View {
    @Environment(AppModel.self) private var model
    @State private var sidebar: SidebarItem? = .home
    // .automatic opened a portrait iPad on a blank "Pick a place" page with the list hidden behind the sidebar button;
    // .all shows the list next to the place (and the sidebar too, in landscape)
    @State private var columns: NavigationSplitViewVisibility = .all

    enum SidebarItem: Hashable { case home, guide(Guide), map, saved, about }

    var body: some View {
        @Bindable var model = model
        NavigationSplitView(columnVisibility: $columns) {
            List(selection: $sidebar) {
                Label("Home", systemImage: "house").tag(SidebarItem.home)
                Section {
                    ForEach(Guide.allCases) { g in
                        Label(g.title, systemImage: g.systemImage).tag(SidebarItem.guide(g))
                    }
                } header: { Text("Guides") }
                Section {
                    Label("Map", systemImage: "map").tag(SidebarItem.map)
                    Label("Saved", systemImage: "heart").tag(SidebarItem.saved)
                    Label("About", systemImage: "info.circle").tag(SidebarItem.about)
                }
            }
            .navigationTitle("Texas Eats")
        } content: {
            switch sidebar {
            // .id: each guide starts fresh (its own sort, search and location request), not with the last guide's state
            case .guide(let g): GuideListView(guide: g, selection: $model.selectedPlace).id(g)
            case .map: MapScreen(selection: $model.selectedPlace)
            case .saved: SavedView(selection: $model.selectedPlace)
            // About is a page to read, so it gets the wide column; Home stays beside it
            case .home, .about, nil: HomeView()
            }
        } detail: {
            if sidebar == .about {
                NavigationStack { AboutView() }
            } else if let p = model.selectedPlace {
                NavigationStack { PlaceDetailView(place: p) }.id(p.id)
            } else {
                ContentUnavailableView("Pick a place", systemImage: "fork.knife", description: Text("Choose a Cuban spot, a seafood shack or any restaurant to see its details."))
            }
        }
        .navigationSplitViewStyle(.balanced)
        .tint(Theme.green)
        .onAppear { show(model.tab) }
        .onChange(of: model.tab) { _, t in show(t) }
        .onChange(of: model.selectedGuide) { _, g in if let g { sidebar = .guide(g) } }
        .onChange(of: model.guideRequest) { _, _ in if let g = model.selectedGuide { sidebar = .guide(g) } }
        // the sidebar choice is the model's too, so an iPhone-size layout (Split View, Stage Manager) opens on the same list
        .onChange(of: sidebar) { _, item in remember(item) }
        // "Surprise me" on Home beside About: show the place, not About
        .onChange(of: model.selectedPlace) { _, p in if p != nil && sidebar == .about { sidebar = .home } }
    }

    private func show(_ tab: AppModel.Tab) {
        switch tab {
        case .map: sidebar = .map
        case .saved: sidebar = .saved
        case .about: sidebar = .about
        case .guides: sidebar = model.selectedGuide.map { .guide($0) } ?? .home
        }
    }

    private func remember(_ item: SidebarItem?) {
        switch item {
        case .guide(let g):
            if model.tab != .guides { model.tab = .guides }
            if model.selectedGuide != g { model.selectedGuide = g }
        case .home, nil:
            if model.tab != .guides { model.tab = .guides }
            if model.selectedGuide != nil { model.selectedGuide = nil }
        case .map: if model.tab != .map { model.tab = .map }
        case .saved: if model.tab != .saved { model.tab = .saved }
        case .about: if model.tab != .about { model.tab = .about }
        }
    }
}
