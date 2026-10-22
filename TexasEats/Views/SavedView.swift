import SwiftUI

struct SavedView: View {
    @Environment(AppModel.self) private var model
    var selection: Binding<Place?>? = nil
    @State private var pushed: Place?

    var body: some View {
        let places = model.savedPlaces
        List {
            if places.isEmpty {
                ContentUnavailableView("Nothing saved yet", systemImage: "heart",
                                       description: Text("Tap the heart on any place to keep it here for your next trip."))
            }
            ForEach(places) { p in
                row(p)
                    // the app tint (flag blue) overrode the destructive red
                    .swipeActions { Button("Remove", role: .destructive) { model.toggleSaved(p) }.tint(Theme.red) }
            }
        }
        .listStyle(.plain)
        .navigationTitle("Saved")
        .navigationDestination(item: $pushed) { PlaceDetailView(place: $0) }
        // iPhone-size: the open place is also the model's, so an iPad layout opens on it; and the reverse after an iPad layout
        .onChange(of: pushed) { _, p in if let p { model.selectedPlace = p } }
        .onChange(of: model.handoffPlace, initial: true) { _, p in
            guard selection == nil, model.tab == .saved, let p else { return }
            model.handoffPlace = nil
            pushed = p
        }
    }

    @ViewBuilder
    private func row(_ p: Place) -> some View {
        if let selection {
            // iPad: the place opens beside the list, and its row stays highlighted like the guides' rows
            Button { selection.wrappedValue = p } label: { PlaceRow(place: p) }
                .listRowBackground(selection.wrappedValue?.id == p.id ? Theme.surface2 : Theme.surface)
                .accessibilityAddTraits(selection.wrappedValue?.id == p.id ? .isSelected : [])
        } else {
            // iPhone: a row with a chevron, like every other list, so it reads as tappable
            Button { pushed = p } label: {
                HStack {
                    PlaceRow(place: p)
                    Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.rule2)
                        .accessibilityHidden(true)
                }
            }
        }
    }
}
