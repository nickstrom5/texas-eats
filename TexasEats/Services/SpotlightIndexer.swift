import CoreSpotlight
import UniformTypeIdentifiers

/// Puts the hand-checked and honored places (Cuban spots, stone crabs, seafood shacks, MICHELIN and James Beard places, the oldest
/// ones) into iPhone search, so "brisket lockhart" in Spotlight can open the place in the app.
enum SpotlightIndexer {
    static let domain = "places"
    private static let versionKey = "spotlightIndexedGenerated"

    static func indexIfNeeded(_ places: [Place], generated: String, defaults: UserDefaults = .standard) {
        guard CSSearchableIndex.isIndexingAvailable(), defaults.string(forKey: versionKey) != generated else { return }
        let featured = places.filter { !$0.isVenue && ($0.isHonored || $0.handChecked) && !$0.isChain }
        let items = featured.map { p -> CSSearchableItem in
            let attrs = CSSearchableItemAttributeSet(contentType: .content)
            attrs.title = p.name
            var kinds: [String] = []
            if p.handChecked {
                for (tag, label) in [(PlaceTags.bbq, "Barbecue"), (.texMex, "Tex-Mex"), (.taqueria, "Taquería"), (.kolache, "Kolaches"),
                                     (.chickenFried, "Chicken-fried steak")] where p.tags.contains(tag) {
                    kinds.append(label)
                }
            }
            if let m = p.michelin.label { kinds.append(m) }
            if let jb = p.jamesBeardLabel { kinds.append(jb) }
            attrs.contentDescription = ([kinds.joined(separator: " · ")] + [p.fullAddress]).filter { !$0.isEmpty }.joined(separator: "\n")
            attrs.keywords = kinds + [p.city, p.cuisine, "Texas"].compactMap { $0 }
            if let c = p.coordinate { attrs.latitude = NSNumber(value: c.latitude); attrs.longitude = NSNumber(value: c.longitude); attrs.supportsNavigation = true }
            return CSSearchableItem(uniqueIdentifier: p.id, domainIdentifier: domain, attributeSet: attrs)
        }
        CSSearchableIndex.default().deleteSearchableItems(withDomainIdentifiers: [domain]) { _ in
            CSSearchableIndex.default().indexSearchableItems(items) { error in
                if error == nil { defaults.set(generated, forKey: versionKey) }
            }
        }
    }
}
