import XCTest
@testable import TexasEats

/// The Filters sheet's "Bib Gourmand" switch: it keeps every Bib Gourmand place and nothing else, in every guide, on the map
/// and in search, and with the other filters.
@MainActor
final class BibGourmandFilterTests: XCTestCase {

    private func bundled() async -> AppModel {
        let m = AppModel(defaults: UserDefaults(suiteName: "bib-\(UUID().uuidString)")!)
        await m.load()
        XCTAssertTrue(m.isLoaded, m.loadError ?? "")
        return m
    }

    /// What's wrong with a list made with the switch on: a place that isn't a Bib Gourmand, or a Bib Gourmand that the guide
    /// and the other filters keep but the list left out. Empty when it's right.
    static func problems(_ kept: [Place], from all: [Place], guide: Guide, others: Filters) -> [String] {
        let ids = Set(kept.map(\.id))
        let wrong = kept.filter { $0.michelin != .bib }.map { "\(guide.title): not a Bib Gourmand: \($0.name)" }
        let missed = all.filter { $0.michelin == .bib && guide.includes($0) && others.allows($0) && !ids.contains($0.id) }
            .map { "\(guide.title): Bib Gourmand left out: \($0.name)" }
        return wrong + missed
    }

    /// Every guide's list (Near Me needs a location), with and without the other filters.
    private func allProblems(_ m: AppModel) -> [String] {
        var out: [String] = []
        for others in [Filters(), { var f = Filters(); f.hideChains = true; f.confirmedOnly = true; return f }()] {
            var on = others; on.bibGourmand = true
            m.filters = on
            for g in Guide.allCases where g != .nearMe {
                out += Self.problems(m.list(g, sort: g.defaultSort, search: "", here: nil), from: m.places, guide: g, others: others)
            }
        }
        return out
    }

    func testKeepsEveryBibGourmandAndNothingElse() async {
        let m = await bundled()
        XCTAssertGreaterThanOrEqual(m.bibCount, 5, "the bundled data has Bib Gourmands")
        XCTAssertEqual(m.bibCount, m.places.filter { $0.michelin == .bib && !$0.isVenue }.count)
        XCTAssertEqual(allProblems(m), [])
        m.filters = Filters(); m.filters.bibGourmand = true
        XCTAssertEqual(m.filters.activeCount, 1, "counts as one filter")
        XCTAssertEqual(m.list(.all, sort: .name, search: "", here: nil).count, m.bibCount, "the switch's count is what it shows")
    }

    func testSearchAndMap() async {
        let m = await bundled()
        m.filters.bibGourmand = true
        for p in m.places where p.michelin == .bib && !p.isVenue {
            let hits = m.list(.all, sort: .name, search: p.name, here: nil)
            XCTAssertTrue(hits.allSatisfy { $0.michelin == .bib }, "\(p.name): a search with the switch on returned a place that isn't a Bib Gourmand")
            XCTAssertTrue(hits.contains { $0.id == p.id }, "\(p.name): its own name didn't find it with the switch on")
        }
        // MapScreen's layers filter the same way
        let map = m.places.filter { Guide.all.includes($0) && m.filters.allows($0) && $0.coordinate != nil }
        XCTAssertEqual(Set(map.map(\.id)), Set(m.places.filter { $0.michelin == .bib && !$0.isVenue && $0.coordinate != nil }.map(\.id)))
    }

    /// Filters saved by a build without the switch still load (and keep what was set).
    func testOlderSavedFiltersStillLoad() throws {
        let old = #"{"town":"Austin","hideChains":true,"confirmedOnly":false,"includeNonRestaurants":false}"#
        let f = try JSONDecoder().decode(Filters.self, from: Data(old.utf8))
        XCTAssertEqual(f.town, "Austin"); XCTAssertTrue(f.hideChains); XCTAssertFalse(f.bibGourmand)
        var on = Filters(); on.bibGourmand = true
        XCTAssertEqual(try JSONDecoder().decode(Filters.self, from: JSONEncoder().encode(on)), on)
    }

    /// The check above can fail: a list that ignores the switch, drops a Bib Gourmand, or lets a starred place in is caught.
    func testCheckCatchesABrokenFilter() async {
        let m = await bundled()
        let all = m.places.filter { Guide.all.includes($0) && !$0.isVenue }
        XCTAssertFalse(Self.problems(all, from: m.places, guide: .all, others: Filters()).isEmpty, "ignoring the switch must be caught")
        let bibs = all.filter { $0.michelin == .bib }
        XCTAssertFalse(Self.problems(Array(bibs.dropFirst()), from: m.places, guide: .all, others: Filters()).isEmpty, "a missing Bib Gourmand must be caught")
        let starred = all.filter { $0.michelin.rawValue >= Michelin.bib.rawValue }
        XCTAssertFalse(Self.problems(starred, from: m.places, guide: .all, others: Filters()).isEmpty, "a starred place must be caught")
    }
}
