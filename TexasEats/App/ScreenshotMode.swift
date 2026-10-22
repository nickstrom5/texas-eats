import Foundation
import CoreLocation
import UIKit

/// `-screenshot <name>` opens one screen with fixed state for App Store screenshots (scripts/capture-screenshots.sh).
/// Names: home, bbq, taqueria, kolache, detail, map, honors, oldest, saved, about.
enum ScreenshotMode {
    /// Debug builds only: an App Store build ignores the launch argument, so no one can reach seeded screens or fake locations.
    static var name: String? {
        #if DEBUG
        let args = ProcessInfo.processInfo.arguments
        guard let i = args.firstIndex(of: "-screenshot"), i + 1 < args.count else { return nil }
        return args[i + 1]
        #else
        return nil
        #endif
    }
    static var isActive: Bool { name != nil }

    @MainActor
    static func apply(to model: AppModel) {
        guard let name, model.isLoaded else { return }
        model.filters = Filters()
        // downtown Austin (Congress Ave at 6th St), so "nearest" lists have distances without a permission prompt
        model.screenshotLocation = CLLocation(latitude: 30.2686, longitude: -97.7428)
        // by name and town, ignoring case, so a rebuild with a slightly different casing still finds the place; the hand-checked one
        // first (Austin also inspects a second "Franklin Barbecue" facility at 1001 E 3rd St)
        let pick = { (n: String, town: String?) -> Place? in
            let hits = model.places.filter { $0.name.caseInsensitiveCompare(n) == .orderedSame && (town == nil || $0.city == town) }
            return hits.first(where: \.handChecked) ?? hits.first
        }
        for p in [pick("Franklin Barbecue", "Austin"), pick("Joe's Bakery & Coffee Shop", "Austin"), pick("Gaido's", "Galveston")]
            .compactMap({ $0 }) where !model.isSaved(p) {
            model.toggleSaved(p)
        }
        let open = { (g: Guide) in model.tab = .guides; model.selectedGuide = g; model.guidesPath = [.guide(g)] }
        switch name {
        case "bbq": open(.bbq)
        case "taqueria": open(.taqueria)
        case "kolache":
            // from West, Texas (the Czech kolache town on I-35), so the nearest bakeries are a short drive
            model.screenshotLocation = CLLocation(latitude: 31.8024, longitude: -97.0925)
            open(.kolache)
        case "honors": open(.honors)
        case "oldest": open(.oldest)
        case "detail":
            open(.bbq)
            if let p = pick("Micklethwait Craft Meats", "Austin") ?? model.places.first { model.selectedPlace = p; model.guidesPath.append(.place(p)) }
        case "map": model.tab = .map
        case "saved": model.tab = .saved
        case "about": model.tab = .about
        default: model.tab = .guides; model.selectedGuide = nil
        }
        // iPad shows the place column next to every list, so give each shot a place instead of "Pick a place": a different
        // honored or hand-checked one per shot.
        guard UIDevice.current.userInterfaceIdiom == .pad, model.selectedPlace == nil else { return }
        let place: Place? = switch name {
        case "home": pick("Joe's Bakery & Coffee Shop", "Austin")
        case "bbq": pick("Franklin Barbecue", "Austin")
        case "map": pick("Dai Due", "Austin")
        case "honors": pick("Barley Swine", "Austin")
        case "oldest": pick("Gaido's", "Galveston")
        case "saved": pick("Gaido's", "Galveston")
        case "about": nil
        default: pick("Franklin Barbecue", "Austin")
        }
        model.selectedPlace = place
    }
}
