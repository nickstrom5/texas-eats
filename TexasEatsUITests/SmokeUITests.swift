import XCTest
import CoreLocation

/// Taps through every screen and control a reviewer is likely to touch, on iPhone (tabs) and iPad (split view).
/// Pass = nothing crashes and each screen shows what it should. Slow (network place cards, map tiles), so CI runs
/// only the unit tests; run this before every App Store submission:
/// xcodebuild test -scheme TexasEats -only-testing:TexasEatsUITests -destination 'id=<sim>'
final class SmokeUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
        // the location prompt can appear on Near Me or the Nearest sort; answer it like a first-time user would
        addUIInterruptionMonitor(withDescription: "Location") { alert in
            for b in ["Allow While Using App", "Allow Once", "Don’t Allow", "Don't Allow"] where alert.buttons[b].exists {
                alert.buttons[b].tap(); return true
            }
            return false
        }
        app.launch()
    }

    private func button(containing text: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@", text)).firstMatch
    }

    /// A Home guide card. "Surprise me with a Texas classic" is excluded so a title can't match it.
    private func guideCard(_ title: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label CONTAINS[c] %@ AND NOT (label CONTAINS[c] 'Surprise')", title)).firstMatch
    }

    private func text(containing text: String) -> XCUIElement {
        app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", text)).firstMatch
    }

    private func waitFor(_ e: XCUIElement, _ seconds: TimeInterval = 10, _ what: String) {
        XCTAssertTrue(e.waitForExistence(timeout: seconds), "missing: \(what)")
    }

    /// Waits until an element stops moving: a tap on a sheet that's still sliding up can land on the animation (QA DEV-T1).
    private func waitUntilSettled(_ e: XCUIElement, timeout: TimeInterval = 5) {
        var last = CGRect.null
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            let f = e.frame
            if f == last && e.isHittable { return }
            last = f
            Thread.sleep(forTimeInterval: 0.3)
        }
    }

    private func scrollTo(_ e: XCUIElement, max: Int = 8) {
        var n = 0
        while !e.isHittable && n < max { app.swipeUp(); n += 1 }
    }

    private var isPad: Bool { UIDevice.current.userInterfaceIdiom == .pad }

    /// Place detail: save, share, then Apple Maps card (or the "not on Apple Maps" fallback). Apple's card goes last: in the simulator it
    /// stays up and covers the toolbar, and the next step relaunches the app anyway.
    private func exerciseDetail(named name: String) {
        waitFor(text(containing: name), 10, "detail for \(name)")
        // the heart, by its identifier: "Saved" alone also matches the Saved tab, which once let this check pass with nothing saved
        let heart = app.buttons["saveHeart"]
        waitFor(heart, 5, "the heart")
        if heart.label == "Saved" {   // saved by an earlier run on this simulator (screenshot mode saves it too): start from unsaved
            heart.tap()
            let unsaved = expectation(for: NSPredicate(format: "label != 'Saved'"), evaluatedWith: heart)
            wait(for: [unsaved], timeout: 5)
        }
        heart.tap()
        let saved = expectation(for: NSPredicate(format: "label == 'Saved'"), evaluatedWith: heart)
        wait(for: [saved], timeout: 5)
        let share = app.buttons["Share"]
        if share.exists {
            share.tap()
            Thread.sleep(forTimeInterval: 1.5)
            let close = app.buttons.matching(NSPredicate(format: "label ==[c] 'Close' OR label ==[c] 'Cancel'")).firstMatch
            if close.exists { close.tap() } else { app.swipeDown(velocity: .fast) }
        }
        let card = button(containing: "Ratings, hours")
        waitFor(card, 5, "Apple Maps button")
        card.tap()
        // Apple's place card sheet, our "no listing" alert, or (offline, throttled) our "couldn't reach" alert
        let fallback = app.alerts["Not on Apple Maps"]
        let failed = app.alerts["Couldn't reach Apple Maps"]
        let deadline = Date().addingTimeInterval(15)
        while Date() < deadline {
            if fallback.exists { fallback.buttons["OK"].tap(); break }
            if failed.exists { failed.buttons["Cancel"].tap(); break }
            if !heart.isHittable { break }   // the sheet is up
            Thread.sleep(forTimeInterval: 0.5)
        }
        XCTAssertEqual(app.state, .runningForeground)
    }

    /// A clean start for each section, so one screen's navigation state can't strand the next (also proves saved places persist).
    private func fresh() {
        app.terminate()
        app.launch()
        waitFor(text(containing: "BBQ, Tex-Mex & Taquerías"), 15, "home header")
    }

    func testTourEveryScreen() throws {
        if isPad { try padTour(); return }
        waitFor(text(containing: "BBQ, Tex-Mex & Taquerías"), 15, "home header")

        // Barbecue Joints: sort, filters, search
        guideCard("Barbecue Joints").tap()
        waitFor(app.navigationBars["Barbecue Joints"], 5, "Barbecue list")
        waitFor(text(containing: "places ·"), 5, "list count header")
        app.buttons["Sort"].tap()
        waitFor(app.buttons["A to Z"], 3, "sort menu"); app.buttons["A to Z"].tap()
        waitFor(text(containing: "A to Z"), 3, "sorted header")
        app.buttons["Filters"].tap()
        waitFor(app.navigationBars["Filters"], 3, "filters sheet")
        // tap the switch itself (its right edge); a tap on the middle of a Toggle row lands on the label
        let hide = app.switches.matching(NSPredicate(format: "label CONTAINS 'Hide chains'")).firstMatch
        waitFor(hide, 3, "hide-chains toggle")
        waitUntilSettled(hide)
        hide.coordinate(withNormalizedOffset: CGVector(dx: 0.93, dy: 0.5)).tap()
        // on a busy Mac the first tap can land while the sheet is still settling; one more try, then a real failure
        Thread.sleep(forTimeInterval: 1.5)
        if (hide.value as? String) != "1" { hide.coordinate(withNormalizedOffset: CGVector(dx: 0.93, dy: 0.5)).tap() }
        let on = expectation(for: NSPredicate(format: "value == '1'"), evaluatedWith: hide)
        wait(for: [on], timeout: 5)
        app.buttons["Done"].tap()
        waitFor(text(containing: "1 filter on"), 3, "active-filter row")
        button(containing: "Clear").tap()
        XCTAssertFalse(text(containing: "filter on").waitForExistence(timeout: 1), "filters cleared")
        let search = app.searchFields.firstMatch
        if !search.exists { app.swipeDown() }
        waitFor(search, 3, "search field"); search.tap(); search.typeText("miami")
        waitFor(text(containing: "places ·"), 3, "search results header")

        // the full directory → a known place → Apple Maps card, save, share
        fresh()
        button(containing: "Search every restaurant").tap()
        let search2 = app.searchFields.firstMatch
        waitFor(search2, 5, "directory search"); search2.tap(); search2.typeText("franklin barb")
        let joes = button(containing: "Franklin Barbecue")
        waitFor(joes, 5, "Franklin in results"); joes.tap()
        exerciseDetail(named: "FRANKLIN BARBECUE")

        // every other guide opens with a list
        for g in ["Tex-Mex", "Taquerías", "MICHELIN & James Beard", "Brewpubs", "Bar Sales", "Inspection Scores", "Near Me"] {
            fresh()
            let card = guideCard(g)
            scrollTo(card)
            card.tap()
            if g == "Near Me" { app.swipeDown() }   // any interaction lets the monitor answer the location prompt (a tap could open a row)
            waitFor(app.navigationBars[g], 5, "\(g) list")
            if g != "Near Me" { waitFor(text(containing: "places ·"), 5, "\(g) count header") }
        }

        // surprise me
        fresh()
        let surprise = button(containing: "Surprise me")
        scrollTo(surprise); surprise.tap()
        waitFor(button(containing: "Ratings, hours"), 5, "a random Texas pick")

        // Map: every layer
        fresh()
        app.tabBars.buttons["Map"].tap()
        // Inspected last: its ~6,000 statewide pins make any later query of this screen time out, so the app relaunches after it
        for l in ["Barbecue", "Honors", "Everything", "Texas picks", "Inspected"] {
            let chip = app.buttons[l]
            waitFor(chip, 5, "map layer \(l)")
            if !chip.isHittable { app.scrollViews.firstMatch.swipeLeft() }
            if !chip.isHittable { app.scrollViews.firstMatch.swipeRight(); app.scrollViews.firstMatch.swipeRight() }
            chip.tap()
            // statewide, Everything asks you to zoom in instead of drawing 80,000 pins
            waitFor(text(containing: l == "Everything" ? "Zoom in to a town" : "tap a pin"), 5, "map hint for \(l)")
        }

        // Saved: Franklin, saved earlier, survived relaunches; remove it
        fresh()
        app.tabBars.buttons["Saved"].tap()
        let saved = button(containing: "Franklin Barbecue")
        waitFor(saved, 5, "saved place")
        saved.swipeLeft()
        if app.buttons["Remove"].waitForExistence(timeout: 2) { app.buttons["Remove"].tap() }

        // About
        app.tabBars.buttons["About"].tap()
        waitFor(text(containing: "TEXAS EATS"), 5, "about header")
        let privacy = app.buttons["Privacy policy"].exists ? app.buttons["Privacy policy"] : app.links["Privacy policy"]
        scrollTo(privacy)
        XCTAssertTrue(privacy.exists, "privacy link")
        XCTAssertEqual(app.state, .runningForeground)
    }

    /// iPad sidebar row. The rows themselves carry no label; the name is a text inside the "Sidebar" list.
    private func sidebarItem(_ name: String) -> XCUIElement {
        app.collectionViews["Sidebar"].staticTexts[name]
    }

    private func padTour() throws {
        // iPad opens on Home in portrait, and a Home card opens its guide
        waitFor(text(containing: "BBQ, Tex-Mex & Taquerías"), 15, "Home at launch in portrait")
        guideCard("Barbecue Joints").tap()
        waitFor(app.navigationBars["Barbecue Joints"], 5, "a Home card opens its guide on iPad")
        XCUIDevice.shared.orientation = .landscapeLeft     // all three columns
        Thread.sleep(forTimeInterval: 1.5)
        for g in ["Tex-Mex", "Taquerías", "MICHELIN & James Beard", "Inspection Scores", "Bar Sales", "All Restaurants", "Barbecue Joints"] {
            let item = sidebarItem(g)
            waitFor(item, 5, "sidebar \(g)"); item.tap()
            waitFor(app.navigationBars[g], 5, "\(g) list")
        }
        let search = app.searchFields.firstMatch
        if !search.exists { app.swipeDown() }
        waitFor(search, 5, "search"); search.tap(); search.typeText("versailles")
        let row = button(containing: "Versailles")
        waitFor(row, 5, "Versailles in results"); row.tap()
        exerciseDetail(named: "VERSAILLES")
        // Apple's place card is still up over the split view: a tap outside it (or a swipe down) closes it
        for _ in 0..<3 where !sidebarItem("Map").isHittable {
            app.coordinate(withNormalizedOffset: CGVector(dx: 0.03, dy: 0.08)).tap()
            Thread.sleep(forTimeInterval: 1)
            if !sidebarItem("Map").isHittable { app.swipeDown(velocity: .fast); Thread.sleep(forTimeInterval: 1) }
        }
        for s in ["Map", "Saved", "About"] {
            let item = sidebarItem(s)
            waitFor(item, 5, "sidebar \(s)"); item.tap()
        }
        waitFor(text(containing: "TEXAS EATS"), 5, "about header")
        XCUIDevice.shared.orientation = .portrait
        Thread.sleep(forTimeInterval: 1.5)
        XCTAssertEqual(app.state, .runningForeground)
    }

    func testEverythingLayerFillsInWhenZoomed() {
        if isPad {
            XCUIDevice.shared.orientation = .landscapeLeft
            waitFor(sidebarItem("Map"), 15, "sidebar Map"); sidebarItem("Map").tap()
        } else {
            waitFor(text(containing: "BBQ, Tex-Mex & Taquerías"), 15, "home header")
            app.tabBars.buttons["Map"].tap()
        }
        let chip = app.buttons["Everything"]
        waitFor(chip, 5, "Everything chip")
        if !chip.isHittable { app.scrollViews.firstMatch.swipeLeft() }
        chip.tap()
        waitFor(text(containing: "Zoom in to a town"), 5, "zoom hint statewide")
        let map = app.maps.firstMatch
        for _ in 0..<6 { map.doubleTap(); Thread.sleep(forTimeInterval: 0.8) }
        waitFor(text(containing: "places here"), 10, "restaurants appear once zoomed in")
        XCTAssertEqual(app.state, .runningForeground)
        if isPad { XCUIDevice.shared.orientation = .portrait }
    }

    /// "My location" moves the map to you at town level, which also fills in the Everything layer.
    /// The simulator's own location resets to Apple's campus, so each location test sets where "you" are.
    private func openMapEverything(at here: CLLocation) {
        // a clean slate: scripts/capture-screenshots.sh revokes location, and the last test left the simulator somewhere else.
        // Resetting asks again (the interruption monitor allows it), and relaunching makes the app's first fix this one.
        app.resetAuthorizationStatus(for: .location)
        XCUIDevice.shared.location = XCUILocation(location: here)
        app.terminate(); app.launch()
        if isPad {
            XCUIDevice.shared.orientation = .landscapeLeft
            waitFor(sidebarItem("Map"), 15, "sidebar Map"); sidebarItem("Map").tap()
        } else {
            waitFor(text(containing: "BBQ, Tex-Mex & Taquerías"), 15, "home header")
            app.tabBars.buttons["Map"].tap()
        }
        let chip = app.buttons["Everything"]
        waitFor(chip, 5, "Everything chip")
        if !chip.isHittable { app.scrollViews.firstMatch.swipeLeft() }
        chip.tap()
        waitFor(text(containing: "Zoom in to a town"), 5, "zoom hint statewide")
        app.buttons["My location"].tap()
        chip.tap()    // an interaction, so the monitor can answer the permission prompt if it appears
    }

    func testMyLocationCentersTheMap() {
        openMapEverything(at: CLLocation(latitude: 30.2686, longitude: -97.7428))   // downtown Austin
        // not a full staticTexts dump here: with the map filled in, hundreds of pins make that query time out
        waitFor(text(containing: "places here"), 15, "map moved to the simulated location and filled in")
        if isPad { XCUIDevice.shared.orientation = .portrait }
    }

    /// App Review is usually in California: the map says so and stays on Texas rather than showing an empty map.
    /// The Bib Gourmand switch turns the MICHELIN guide into Bib Gourmands only: no starred place is left on screen.
    func testBibGourmandFilter() throws {
        if isPad { throw XCTSkip("iPhone flow; the filter itself is covered by BibGourmandFilterTests") }
        waitFor(text(containing: "BBQ, Tex-Mex & Taquerías"), 15, "home header")
        let card = guideCard("MICHELIN & James Beard")
        scrollTo(card)
        card.tap()
        waitFor(text(containing: "places ·"), 5, "honors list")
        app.buttons["Filters"].tap()
        waitFor(app.navigationBars["Filters"], 3, "filters sheet")
        let bib = app.switches.matching(NSPredicate(format: "label BEGINSWITH 'Bib Gourmand ('")).firstMatch
        // below the Show switches: a swipe raises the sheet to full height and scrolls to it
        for _ in 0..<6 where !(bib.exists && bib.isHittable) { app.swipeUp() }
        waitFor(bib, 3, "Bib Gourmand switch with its count")
        waitUntilSettled(bib)
        bib.coordinate(withNormalizedOffset: CGVector(dx: 0.93, dy: 0.5)).tap()
        wait(for: [expectation(for: NSPredicate(format: "value == '1'"), evaluatedWith: bib)], timeout: 3)
        app.buttons["Done"].tap()
        waitFor(text(containing: "1 filter on"), 3, "active-filter row")
        waitFor(text(containing: "Bib Gourmand"), 5, "a Bib Gourmand row")
        XCTAssertFalse(text(containing: "MICHELIN Star").exists, "a starred place is still listed")
        button(containing: "Clear").tap()
        XCTAssertTrue(text(containing: "MICHELIN Star").waitForExistence(timeout: 5), "cleared: the starred places are back")
    }

    func testMyLocationOutsideTexas() {
        openMapEverything(at: CLLocation(latitude: 37.3349, longitude: -122.009))
        waitFor(text(containing: "outside Texas"), 15, "the outside-Texas note")
        XCTAssertTrue(text(containing: "Zoom in to a town").waitForExistence(timeout: 8), "the map stayed statewide")
        if isPad { XCUIDevice.shared.orientation = .portrait }
    }

    /// Apple's accessibility audit on the main iPhone screens. Prints every issue (prefixed AUDIT) instead of failing,
    /// so a run lists them all; read the log and fix what's ours (system bars and Apple's place card aren't).
    func testAccessibilityAudit() throws {
        if isPad { return }
        waitFor(text(containing: "BBQ, Tex-Mex & Taquerías"), 15, "home header")
        func audit(_ screen: String) throws {
            try app.performAccessibilityAudit { issue in
                let el = issue.element.map { "\($0.elementType.rawValue) '\($0.label.prefix(40))'" } ?? "-"
                print("AUDIT [\(screen)] \(issue.auditType.rawValue) | \(issue.compactDescription) | \(el)")
                return true
            }
        }
        try audit("home")
        guideCard("Barbecue Joints").tap()
        waitFor(text(containing: "places ·"), 5, "Barbecue list")
        try audit("bbq")
        app.buttons.matching(NSPredicate(format: "label CONTAINS ' · '")).firstMatch.tap()
        waitFor(button(containing: "Ratings, hours"), 5, "a place")
        try audit("detail")
        app.tabBars.buttons["About"].tap()
        try audit("about")
        // not the Map tab: auditing thousands of MapKit annotations times out, and those views are Apple's
    }

    func testLaunchIsQuick() throws {
        // the bundle decodes off the main thread; the home screen should be up well within a few seconds. The Mac is shared with other
        // builds and simulators (and this test's own build just ran), and a time measured while it's saturated says nothing about the
        // app: wait up to three minutes for the load to settle, and don't judge a launch measured under load.
        let cores = Double(ProcessInfo.processInfo.activeProcessorCount)
        var load = [Double](repeating: 0, count: 3)
        let settle = Date().addingTimeInterval(180)
        while getloadavg(&load, 3) == 3, load[0] > cores * 1.5, Date() < settle { Thread.sleep(forTimeInterval: 5) }
        app.terminate()
        let start = Date()
        app.launch()
        // [c]: the home header may be set in capitals
        let ready = isPad ? app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'places ·' OR label CONTAINS[c] 'BBQ, Tex-Mex & Taquerías'")).firstMatch
                          : text(containing: "BBQ, Tex-Mex & Taquerías")
        XCTAssertTrue(ready.waitForExistence(timeout: 30), "home didn't appear")
        let secs = Date().timeIntervalSince(start)
        print("launch to home: \(String(format: "%.2f", secs)) s (load average \(String(format: "%.1f", load[0])))")
        if getloadavg(&load, 3) == 3, load[0] > cores * 1.5 {
            throw XCTSkip("load average \(Int(load[0])) on \(Int(cores)) cores: launch time not judged (\(String(format: "%.1f", secs)) s)")
        }
        XCTAssertLessThan(secs, 6)
    }
}
