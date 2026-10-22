import XCTest
import CoreLocation
@testable import TexasEats

/// Timings on the bundled data (QA AR-13). The list a guide shows is rebuilt on each search keystroke, each location fix, each
/// filter change and, on iPad, each row tap, so these are the paths a reader feels. Debug builds, so read them relative to each
/// other (the same tests ran before and after the fix: scratchpad qa/swift-fixes.md has both).
@MainActor
final class PerformanceTests: XCTestCase {
    private static var shared: AppModel?
    private let austin = CLLocation(latitude: 30.2686, longitude: -97.7428)

    private func model() async -> AppModel {
        if let m = Self.shared { return m }
        let m = AppModel(defaults: UserDefaults(suiteName: "perf-\(UUID().uuidString)")!)
        await m.load()
        XCTAssertTrue(m.isLoaded, m.loadError ?? "")
        Self.shared = m
        return m
    }

    private var three: XCTMeasureOptions {
        let o = XCTMeasureOptions()
        o.iterationCount = 3
        return o
    }

    /// Launch: read and decode the bundled file and build every Place (the Home screen waits on this).
    func testSpeedLoad() {
        measure(metrics: [XCTClockMetric()], options: three) {
            let m = AppModel(defaults: UserDefaults(suiteName: "perf-load-\(UUID().uuidString)")!)
            let done = expectation(description: "loaded")
            Task { await m.load(); done.fulfill() }
            wait(for: [done], timeout: 60)
            XCTAssertTrue(m.isLoaded)
        }
    }

    /// All Restaurants, A to Z: the first list the directory search opens on.
    func testSpeedSortAToZ() async {
        let places = await model().places.filter { !$0.isVenue }
        measure(metrics: [XCTClockMetric()], options: three) { _ = Ranking.sort(places, by: .name, from: nil) }
    }

    /// Nearest first from downtown Austin: Near Me and every Nearest sort.
    func testSpeedSortNearest() async {
        let places = await model().places.filter { !$0.isVenue }
        let here = austin
        measure(metrics: [XCTClockMetric()], options: three) { _ = Ranking.sort(places, by: .nearest, from: here) }
    }

    /// Typing "buckh" into the directory search: one list per keystroke.
    func testSpeedTyping() async {
        let m = await model()
        measure(metrics: [XCTClockMetric()], options: three) {
            for q in ["b", "bu", "buc", "buck", "buckh"] { _ = m.list(.all, sort: .name, search: q, here: nil) }
        }
    }

    /// Five iPad row taps on Near Me: the list's body runs again with nothing changed.
    func testSpeedRowTaps() async {
        let m = await model()
        let here = austin
        measure(metrics: [XCTClockMetric()], options: three) {
            for _ in 0..<5 { _ = m.list(.nearMe, sort: .nearest, search: "", here: here) }
        }
    }
}
