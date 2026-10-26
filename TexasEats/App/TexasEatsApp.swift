import SwiftUI
import CoreSpotlight

@main
struct TexasEatsApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @State private var model = AppModel()
    @State private var updater = DataUpdater()
    @State private var location = LocationService()

    init() {
        // Large titles in the same compressed black type as the home header, scaled with the reader's text size (capped like
        // DisplayFont, so a title can't swallow the bar). Inline titles are drawn by View.inlineTitle (Design/Theme.swift).
        let green = UIColor(Theme.green)
        UINavigationBar.appearance().largeTitleTextAttributes = [
            .font: UIFontMetrics(forTextStyle: .largeTitle).scaledFont(for: UIFont.systemFont(ofSize: 36, weight: .black, width: .compressed),
                                                                      maximumPointSize: 36 * 1.6),
            .foregroundColor: green,
        ]
        UINavigationBar.appearance().titleTextAttributes = [
            .font: UIFontMetrics(forTextStyle: .headline).scaledFont(for: UIFont.systemFont(ofSize: 19, weight: .heavy, width: .compressed),
                                                                    maximumPointSize: 19 * 1.6),
            .foregroundColor: green,
        ]
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .environment(location)
                .environment(updater)
                .tint(Theme.green)
                .task {
                    await AppData.prepare()
                    await model.load()
                    ScreenshotMode.apply(to: model)
                    if model.isLoaded { updater.checkIfDue(placesInUse: model.places.count) }
                    if model.isLoaded && !ScreenshotMode.isActive {
                        SpotlightIndexer.indexIfNeeded(model.places, generated: model.generated)
                    }
                }
                .onContinueUserActivity(CSSearchableItemActionType) { activity in
                    guard let id = activity.userInfo?[CSSearchableItemActivityIdentifier] as? String else { return }
                    Task {
                        await model.load()
                        if let p = model.place(id: id) { model.tab = .guides; model.selectedPlace = p; model.guidesPath = [.place(p)] }
                    }
                }
        }
        .onChange(of: scenePhase) { _, phase in updater.phaseChanged(to: phase, placesInUse: model.isLoaded ? model.places.count : nil) }
    }
}
