import MapKit
import UIKit

/// Finds the Apple Maps listing for a place so the app can show Apple's own place card (ratings, hours, photos).
/// Those live details are Apple's licensed data, shown in Apple's UI; the app stores none of it.
enum AppleMaps {
    /// Apple's listing, no listing at this spot, or no answer at all (offline, throttled): the last isn't a fact about the place.
    enum Lookup { case found(MKMapItem), notListed, failed }

    static func findItem(for p: Place) async -> Lookup {
        guard let c = p.coordinate else { return .notListed }
        let req = MKLocalSearch.Request()
        req.naturalLanguageQuery = p.name
        req.region = MKCoordinateRegion(center: c, latitudinalMeters: 800, longitudinalMeters: 800)
        req.resultTypes = .pointOfInterest
        let items: [MKMapItem]
        do {
            items = try await MKLocalSearch(request: req).start().mapItems
        } catch {
            // "placemark not found" is Apple saying it has nothing there; any other error means the search didn't get an answer
            if let e = error as? MKError, e.code == .placemarkNotFound { return .notListed }
            return .failed
        }
        let here = CLLocation(latitude: c.latitude, longitude: c.longitude)
        let want = Search.normalize(p.name)
        let scored = items.compactMap { item -> (MKMapItem, Double)? in
            let loc = item.placemark.location ?? here
            let d = loc.distance(from: here)
            guard d < 350 else { return nil }
            let name = Search.normalize(item.name ?? "")
            let words = Set(want.split(separator: " ")), theirs = Set(name.split(separator: " "))
            let shared = Double(words.intersection(theirs).count) / Double(max(1, min(words.count, theirs.count)))
            guard name == want || shared >= 0.5 || name.hasPrefix(want) || want.hasPrefix(name) else { return nil }
            return (item, shared * 2 - d / 350)
        }
        return scored.max { $0.1 < $1.1 }.map { .found($0.0) } ?? .notListed
    }

    /// Fallback: open Apple Maps at the place's name and location.
    static func openInMaps(_ p: Place, directions: Bool = false) {
        guard let c = p.coordinate else {
            if let q = p.fullAddress.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
               let url = URL(string: "https://maps.apple.com/?q=\(q)") { UIApplication.shared.open(url) }
            return
        }
        let item = MKMapItem(placemark: MKPlacemark(coordinate: c))
        item.name = p.name
        item.openInMaps(launchOptions: directions ? [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDriving] : nil)
    }
}
