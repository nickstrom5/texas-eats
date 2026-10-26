import XCTest
import SwiftUI
@testable import TexasEats

/// Over-the-air data updates (OTA-DATA.md): the manifest, versions, every check a download must pass, storage, the choice at
/// launch, and the app's own loader reading a download. The data is a cut-down copy of this app's bundled data, so every
/// check runs the app's real format and loader. All traffic goes to OTAStub; nothing leaves the machine.
/// The same file in every state app (state-prompts/ota/DataUpdatesTests.swift), but for the import line.
@MainActor
final class DataUpdatesTests: XCTestCase {
    var tmp: URL!
    var files: DataFiles!
    var bundle: URL!                       // stands in for the app bundle: the fixture copy dated 2026-10-01
    var layout: DataLayout!
    var defaults: UserDefaults!
    var suite = ""
    var clock = DataVersion.day("2026-10-20")!.addingTimeInterval(12 * 3600)
    let site = URL(string: "https://example.test/state-eats/data/app/")!
    let sitePath = "/state-eats/data/app/"
    var bundled: [String: Any] = [:]
    var bundledPlaces = 0

    override func setUp() async throws {
        tmp = FileManager.default.temporaryDirectory.appending(path: "DataUpdatesTests-\(UUID().uuidString)", directoryHint: .isDirectory)
        files = DataFiles(root: tmp.appending(path: "AppData", directoryHint: .isDirectory))
        bundle = tmp.appending(path: "bundle", directoryHint: .isDirectory)
        bundled = OTAFixture.copy(generated: "2026-10-01")
        try OTAFixture.write(bundled, to: bundle)
        layout = DataLayout(kind: DataLayout.app.kind, bundled: bundle, head: DataLayout.app.head, read: DataLayout.app.read)
        bundledPlaces = try layout.read(bundle).places
        suite = "DataUpdatesTests-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
        OTAStub.reset()
        AppData.reset()
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: tmp)
        defaults.removePersistentDomain(forName: suite)
        OTAStub.reset()
        AppData.reset()
    }

    // MARK: helpers

    func updater(using: DataCopy? = nil, build: Int = 2) -> DataUpdater {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [OTAStub.self]
        let inUse = using ?? layout.bundledCopy
        return DataUpdater(dataURL: site, layout: layout, files: files, inUse: { inUse }, configuration: config, defaults: defaults,
                           build: build, automatic: false, now: { [unowned self] in clock })
    }

    /// Publishes a copy on the stub server the way scripts/publish_app_data.py lays it out under docs/data/app/.
    @discardableResult
    func publish(_ copy: [String: Any], version: String, through: String? = nil, schema: Int = 1, minAppBuild: Int = 1,
                 sha: [String: String] = [:], bytes: [String: Int] = [:], rows: [String: Int] = [:], served: String? = nil,
                 leaveOut: Set<String> = []) throws -> [String: Data] {
        var entries: [String: Any] = [:], out: [String: Data] = [:]
        for (name, obj) in copy {
            let data = try OTAFixture.encode(obj)
            let hash = DataFiles.sha256(data), path = "\(name)-\(hash.prefix(12)).json"
            out[name] = data
            if leaveOut.contains(name) { continue }
            entries[name] = ["path": path, "sha256": sha[name] ?? hash, "bytes": bytes[name] ?? data.count, "rows": rows[name] ?? OTAFixture.rows(name, obj)]
            OTAStub.serve(sitePath + path, data)
        }
        let date = through ?? String(version.prefix(10))
        let manifest: [String: Any] = ["schema": schema, "version": version, "records_through": date, "published": "2026-10-20T11:30:00Z",
                                       "min_app_build": minAppBuild, "files": entries]
        OTAStub.serve(sitePath + "manifest.json", try JSONSerialization.data(withJSONObject: manifest), headers: served.map { ["Date": $0] } ?? [:])
        return out
    }

    var fileRequests: [URLRequest] { OTAStub.requests.filter { !$0.url!.path.hasSuffix("manifest.json") } }
    func stored() throws -> Set<String> { Set(try FileManager.default.contentsOfDirectory(atPath: files.root.path)) }

    /// A newer copy: the bundled fixture dated `date`, with one place renamed (so it differs from the bundle).
    func newer(_ date: String, rename: String = "Updated Place") -> [String: Any] {
        var c = OTAFixture.copy(generated: date)
        OTAFixture.renameFirstPlace(&c, to: rename)
        return c
    }

    // MARK: manifest and versions

    func testManifestDecoding() throws {
        let json = """
        {"schema":1,"version":"2026-10-21.2","records_through":"2026-10-21","published":"2026-10-22T11:30:00Z","min_app_build":3,
         "files":{"places":{"path":"places-0123456789ab.json","sha256":"\(String(repeating: "a", count: 64))","bytes":3627062,"rows":17294}},
         "counts":{"places":17294}}
        """
        let m = try JSONDecoder().decode(DataManifest.self, from: Data(json.utf8))
        XCTAssertEqual(m.schema, 1)
        XCTAssertEqual(m.minAppBuild, 3)
        XCTAssertEqual(m.files["places"]?.rows, 17294)
        XCTAssertEqual(m.dataVersion, DataVersion(date: "2026-10-21", n: 2))
        XCTAssertTrue(m.files.values.allSatisfy(\.wellFormed))
        let bare = try JSONDecoder().decode(DataManifest.self, from: Data(#"{"schema":1,"version":"2026-10-21.1","records_through":"2026-10-21","files":{}}"#.utf8))
        XCTAssertEqual(bare.minAppBuild, 1, "min_app_build defaults to 1")
        let sha = String(repeating: "a", count: 64)
        XCTAssertFalse(DataManifest.File(path: "../../etc/x.json", sha256: sha, bytes: 10, rows: 1).wellFormed, "a path is a file name next to the manifest")
        XCTAssertFalse(DataManifest.File(path: "p.json", sha256: "abc", bytes: 10, rows: 1).wellFormed)
        XCTAssertFalse(DataManifest.File(path: "p.json", sha256: sha, bytes: DataUpdater.maxFileBytes + 1, rows: 1).wellFormed, "size cap")
        XCTAssertFalse(DataManifest.File(path: "p.json", sha256: sha, bytes: 0, rows: 1).wellFormed)
        XCTAssertTrue(DataManifest.validName("detail-south-florida"))
        XCTAssertFalse(DataManifest.validName("../places"))
        XCTAssertFalse(DataManifest.validName("Places"))
        XCTAssertFalse(DataManifest.validName("places.json"))
    }

    func testVersionOrder() {
        let v1 = DataVersion("2026-10-21.1", recordsThrough: "2026-10-21")!
        let v2 = DataVersion("2026-10-21.2", recordsThrough: "2026-10-21")!
        let next = DataVersion("2026-11-04.1", recordsThrough: "2026-11-04")!
        XCTAssertGreaterThan(v2, v1, "a same-day republish is newer")
        XCTAssertGreaterThan(next, v2)
        XCTAssertFalse(v1 > DataVersion("2026-10-21.1", recordsThrough: "2026-10-21")!, "equal isn't newer")
        XCTAssertLessThan(DataVersion.bundled("2026-10-21"), v1, "the bundle is n = 0: a published copy of its date (a correction) is newer")
        XCTAssertGreaterThan(DataVersion.bundled("2026-10-22"), v2, "a later date still wins")
        XCTAssertNil(DataVersion("2026-10-21", recordsThrough: "2026-10-21"), "no counter")
        XCTAssertNil(DataVersion("2026-10-20.1", recordsThrough: "2026-10-21"), "date doesn't match records_through")
        XCTAssertNil(DataVersion("2026-10-21.0", recordsThrough: "2026-10-21"), "the counter starts at 1")
        XCTAssertNil(DataVersion("2026-02-30.1", recordsThrough: "2026-02-30"), "not a real day")
        XCTAssertNil(DataVersion("2026-99-99.1", recordsThrough: "2026-99-99"))
        XCTAssertNil(DataVersion("../x.1", recordsThrough: "../x"))
        XCTAssertNotNil(DataVersion("2028-02-29.1", recordsThrough: "2028-02-29"), "a leap day")
        XCTAssertNotNil(DataVersion("2026-09-06.1", recordsThrough: "2026-09-06"), "read in UTC: Chile skips that local midnight")
    }

    /// The bundled copy's version comes from its head file's "generated", read without parsing the whole file, and for the
    /// app's real bundle it's the date the app's loader reads.
    func testBundledVersionIsTheDataDate() throws {
        XCTAssertEqual(layout.bundledCopy.version, .bundled("2026-10-01"))
        let summary = try XCTUnwrap(Self.realSummary)
        XCTAssertEqual(DataLayout.app.bundledCopy.version, .bundled(summary.generated))
        XCTAssertNotNil(DataVersion.day(summary.generated), "the bundled data is dated")
        XCTAssertGreaterThan(summary.places, 1000)
        // the loader reads every row publish_app_data.py counts, so the rows in a published manifest match what phones read
        for (name, obj) in OTAFixture.source where summary.rows[name] != nil {
            XCTAssertEqual(summary.rows[name], OTAFixture.rows(name, obj), name)
        }
        XCTAssertEqual(Set(summary.rows.keys), Set(OTAFixture.source.keys), "the loader reads every bundled data file")
    }

    // MARK: checks

    func testNewerDataIsDownloadedCheckedAndStored() async throws {
        let copy = newer("2026-10-15")
        let published = try publish(copy, version: "2026-10-15.1")
        let u = updater()
        let outcome = await u.check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .downloaded(recordsThrough: "2026-10-15"))
        XCTAssertEqual(u.waiting, "2026-10-15", "used from the next launch")
        XCTAssertEqual(u.lastCheck, clock)

        // stored: one version folder with every file, current.json naming it, left out of backup
        let cur = try XCTUnwrap(files.current())
        XCTAssertEqual(cur.version, "2026-10-15.1")
        XCTAssertEqual(cur.build, 2)
        XCTAssertEqual(Set(cur.files.keys), Set(copy.keys))
        XCTAssertEqual(try stored(), ["2026-10-15.1", "current.json"])
        for (name, data) in published {
            XCTAssertEqual(try Data(contentsOf: files.folder("2026-10-15.1").appending(path: "\(name).json")), data, name)
        }
        XCTAssertEqual(try files.root.resourceValues(forKeys: [.isExcludedFromBackupKey]).isExcludedFromBackup, true)

        // only the files that changed were downloaded; the rest came from the bundle
        let changed = published.filter { name, data in (try? Data(contentsOf: bundle.appending(path: "\(name).json"))) != data }
        XCTAssertTrue(changed.keys.contains(layout.head))
        XCTAssertEqual(Set(fileRequests.map { $0.url!.lastPathComponent }), Set(changed.map { "\($0.key)-\(DataFiles.sha256($0.value).prefix(12)).json" }))
        if published.count > 2 { XCTAssertLessThan(changed.count, published.count, "unchanged files aren't downloaded") }
        XCTAssertEqual(fileRequests.first?.allowsConstrainedNetworkAccess, false, "data files wait out Low Data Mode")

        // nothing about the person in any request
        XCTAssertEqual(OTAStub.requests.first?.url?.absoluteString, site.absoluteString + "manifest.json")
        for r in OTAStub.requests {
            XCTAssertNil(r.url?.query, "no query")
            XCTAssertEqual(r.httpMethod, "GET")
            XCTAssertNil(r.value(forHTTPHeaderField: "Cookie"))
            XCTAssertEqual(r.value(forHTTPHeaderField: "Accept-Language"), "en", "a fixed language, never the device's")
            XCTAssertEqual(r.value(forHTTPHeaderField: "User-Agent"), DataUpdater.headers["User-Agent"])
        }

        // the next launch reads it with the app's own loader
        let launch = files.choose(layout, build: 2, now: clock)
        XCTAssertTrue(launch.downloaded)
        XCTAssertEqual(launch.version, DataVersion(date: "2026-10-15", n: 1))
        XCTAssertEqual(try layout.read(launch.folder).generated, "2026-10-15")

        // and the next publish replaces it; the folder this run reads stays until the next launch
        let later = newer("2026-10-19", rename: "Later Place")
        try publish(later, version: "2026-10-19.1")
        let u2 = updater(using: launch)
        let outcome2 = await u2.check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome2, .downloaded(recordsThrough: "2026-10-19"))
        XCTAssertEqual(try stored(), ["2026-10-15.1", "2026-10-19.1", "current.json"])
        XCTAssertEqual(files.choose(layout, build: 2, now: clock).version, DataVersion(date: "2026-10-19", n: 1))
        XCTAssertEqual(try stored(), ["2026-10-19.1", "current.json"], "launch removes the copy it no longer reads")
    }

    /// The same version, an older one, or the bundle's own files again: nothing is downloaded or stored.
    func testSameOrOlderIsIgnored() async throws {
        try publish(bundled, version: "2026-10-01.1")
        var outcome = await updater().check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .upToDate, "the first publish of the bundled data: byte for byte what the app has")
        try publish(newer("2026-09-20"), version: "2026-09-20.1")
        outcome = await updater().check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .upToDate, "older than the bundle")
        XCTAssertTrue(fileRequests.isEmpty)
        XCTAssertNil(files.current())

        // a copy already downloaded isn't downloaded again, and neither is an older one
        try publish(newer("2026-10-15"), version: "2026-10-15.1")
        outcome = await updater().check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .downloaded(recordsThrough: "2026-10-15"))
        OTAStub.reset()
        try publish(newer("2026-10-15"), version: "2026-10-15.1")
        outcome = await updater().check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .upToDate, "the waiting copy is the newest on hand")
        try publish(newer("2026-10-10"), version: "2026-10-10.1")
        outcome = await updater(using: files.choose(layout, build: 2, now: clock)).check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .upToDate)
        XCTAssertTrue(fileRequests.isEmpty)

        // a newer format, or one for a newer build, is for newer apps
        try publish(newer("2026-10-19"), version: "2026-10-19.1", schema: 2)
        outcome = await updater().check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .upToDate)
        try publish(newer("2026-10-19"), version: "2026-10-19.1", minAppBuild: 3)
        outcome = await updater().check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .upToDate)
        XCTAssertTrue(fileRequests.isEmpty)
    }

    /// A correction published for the bundle's own date reaches phones still on the bundled data.
    func testSameDateCorrectionReplacesTheBundle() async throws {
        try publish(newer("2026-10-01"), version: "2026-10-01.2")
        let outcome = await updater().check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .downloaded(recordsThrough: "2026-10-01"))
        XCTAssertEqual(files.choose(layout, build: 2, now: clock).version, DataVersion(date: "2026-10-01", n: 2))
    }

    func testShaMismatchIsRejected() async throws {
        try publish(newer("2026-10-15"), version: "2026-10-15.1", sha: [layout.head: String(repeating: "0", count: 64)])
        let u = updater()
        let outcome = await u.check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .failed)
        XCTAssertNil(u.waiting)
        XCTAssertNil(files.current(), "nothing stored")
        XCTAssertEqual(try stored(), [], "no leftovers")
        XCTAssertNil(u.lastCheck, "a failed check isn't a check")
        // the same bad version isn't downloaded again by the next automatic check
        OTAStub.reset()
        try publish(newer("2026-10-15"), version: "2026-10-15.1", sha: [layout.head: String(repeating: "0", count: 64)])
        let again = await u.check(placesInUse: bundledPlaces)
        XCTAssertEqual(again, .upToDate)
        XCTAssertTrue(fileRequests.isEmpty)
        // a corrected publish gets through
        try publish(newer("2026-10-15"), version: "2026-10-15.2")
        let fixed = await u.check(placesInUse: bundledPlaces)
        XCTAssertEqual(fixed, .downloaded(recordsThrough: "2026-10-15"))
    }

    func testWrongByteCountIsRejected() async throws {
        let copy = newer("2026-10-15")
        let size = try OTAFixture.encode(copy[layout.head]!).count
        try publish(copy, version: "2026-10-15.1", bytes: [layout.head: size + 1])
        let outcome = await updater().check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .failed)
        XCTAssertNil(files.current())
    }

    /// Truncated or corrupt JSON with a matching size and hash is bad content: the app's own loader refuses it, and
    /// automatic checks don't download it again.
    func testCorruptOrTruncatedJSONIsRejected() async throws {
        let whole = try OTAFixture.encode(OTAFixture.copy(generated: "2026-10-15")[layout.head]!)
        for bad in [whole.prefix(whole.count / 2), Data("{\"generated\":\"2026-10-15\",\"places\":[{".utf8), Data("not json".utf8)] {
            OTAStub.reset()
            for key in ["data.rejected", "data.lastCheck", "data.lastAttempt"] { defaults.removeObject(forKey: key) }
            var copy = OTAFixture.copy(generated: "2026-10-15")          // only the head file differs from the bundle
            copy[layout.head] = OTAFixture.Raw(data: Data(bad))
            try publish(copy, version: "2026-10-15.1")
            let u = updater()
            let outcome = await u.check(placesInUse: bundledPlaces)
            XCTAssertEqual(outcome, .failed)
            XCTAssertNil(files.current())
            XCTAssertEqual(try stored(), [])
            XCTAssertEqual(fileRequests.count, 1)
            clock += 2 * 3600
            XCTAssertTrue(u.isDue)
            let again = await u.check(placesInUse: bundledPlaces)
            XCTAssertEqual(again, .upToDate, "skipped from now on")
            XCTAssertEqual(fileRequests.count, 1, "not downloaded again")
        }
    }

    func testRowCountOrDateMismatchIsRejected() async throws {
        let copy = newer("2026-10-15")
        try publish(copy, version: "2026-10-15.1", rows: [layout.head: OTAFixture.rows(layout.head, copy[layout.head]!) + 1])
        var outcome = await updater().check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .failed, "rows differ from what the loader read")
        // the manifest says Oct 16, the file says Oct 15
        try publish(copy, version: "2026-10-16.1", through: "2026-10-16")
        outcome = await updater().check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .failed, "dates differ")
        XCTAssertNil(files.current())
    }

    func testBigSwingIsRejected() async throws {
        try publish(newer("2026-10-15"), version: "2026-10-15.1")
        var outcome = await updater().check(placesInUse: Int(Double(bundledPlaces) / 0.7), manual: true)
        XCTAssertEqual(outcome, .failed, "30% fewer places than in use")
        outcome = await updater().check(placesInUse: Int(Double(bundledPlaces) / 1.3) - 1, manual: true)
        XCTAssertEqual(outcome, .failed, "30% more")
        XCTAssertNil(files.current())
        outcome = await updater().check(placesInUse: Int(Double(bundledPlaces) * 1.1), manual: true)
        XCTAssertEqual(outcome, .downloaded(recordsThrough: "2026-10-15"), "10% is within bounds")
    }

    /// The site down, a missing manifest or data file, no network: nothing changes, and the next check tries again.
    func testOfflineAnd404FallBackToBundled() async throws {
        let u = updater()
        OTAStub.offline = true
        var outcome = await u.check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .failed, "offline")
        OTAStub.offline = false
        outcome = await u.check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .failed, "no manifest: 404")
        // a data file that 404s
        let published = try publish(newer("2026-10-15"), version: "2026-10-15.1")
        OTAStub.serve(sitePath + "\(layout.head)-\(DataFiles.sha256(published[layout.head]!).prefix(12)).json", Data(), status: 404)
        outcome = await u.check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .failed)
        XCTAssertNil(files.current())
        XCTAssertEqual(try? stored(), [], "no leftovers")
        XCTAssertNil(u.lastCheck)
        let launch = files.choose(layout, build: 2, now: clock)
        XCTAssertFalse(launch.downloaded, "the app reads its bundled data")
        XCTAssertEqual(launch.folder, bundle)
        // not remembered as bad: an hour later it's tried again and gets through
        try publish(newer("2026-10-15"), version: "2026-10-15.1")
        XCTAssertFalse(u.isDue, "an hour after a failed try")
        clock += 3601
        XCTAssertTrue(u.isDue)
        outcome = await u.check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .downloaded(recordsThrough: "2026-10-15"))
    }

    func testFutureDatesAreRefused() async throws {
        try publish(newer("2026-10-25"), version: "2026-10-25.1", served: "Mon, 19 Oct 2026 12:00:00 GMT")
        var outcome = await updater().check(placesInUse: bundledPlaces, manual: true)
        XCTAssertEqual(outcome, .failed, "more than 3 days after the server's own clock")
        try publish(newer("2026-10-21"), version: "2026-10-21.1", served: "Mon, 19 Oct 2026 12:00:00 GMT")
        outcome = await updater().check(placesInUse: bundledPlaces, manual: true)
        XCTAssertEqual(outcome, .downloaded(recordsThrough: "2026-10-21"), "2 days after")
        // a stored copy dated more than 30 days after the phone's clock is deleted at launch
        clock = DataVersion.day("2026-09-15")!
        XCTAssertFalse(files.choose(layout, build: 2, now: clock).downloaded)
        XCTAssertNil(files.current())
    }

    func testChecksAtMostDaily() async throws {
        let u = updater()
        XCTAssertTrue(u.isDue, "never checked")
        try publish(bundled, version: "2026-10-01.1")
        _ = await u.check(placesInUse: bundledPlaces)
        XCTAssertFalse(u.isDue)
        clock += 23 * 3600
        XCTAssertFalse(u.isDue)
        clock += 3600
        XCTAssertTrue(u.isDue, "a day later")
        OTAStub.reset()
        _ = await u.check(placesInUse: bundledPlaces)
        XCTAssertFalse(u.isDue, "waits an hour after a failed try")
        clock += 3601
        XCTAssertTrue(u.isDue)
        clock -= 30 * 24 * 3600
        XCTAssertTrue(u.isDue, "a clock set back doesn't stop checks")
    }

    // MARK: a newer copy in a different layout

    func testNewerCopyInADifferentLayout() async throws {
        var copy = newer("2026-10-15")
        switch layout.kind {
        case .single:
            // an extra file this app doesn't read is stored with the rest and ignored
            copy["extra-notes"] = ["places": [] as [Any]]
        case .coreDetail:
            // one region's detail file gone, an extra file added
            let gone = copy.keys.filter { $0.hasPrefix("detail-") }.sorted().first!
            copy[gone] = nil
            copy["extra-notes"] = ["places": [] as [Any]]
        case .regions:
            // one region's file renamed and another region dropped from the index
            let regionFiles = copy.keys.filter { $0 != layout.head }.sorted()
            XCTAssertGreaterThanOrEqual(regionFiles.count, 3)
            OTAFixture.renameRegionFile(&copy, head: layout.head, from: regionFiles[0], to: regionFiles[0] + "-new")
            OTAFixture.dropRegionFile(&copy, head: layout.head, regionFiles[1])
        }
        try publish(copy, version: "2026-10-15.1")
        let outcome = await updater().check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .downloaded(recordsThrough: "2026-10-15"))
        let names = Set(try FileManager.default.contentsOfDirectory(atPath: files.folder("2026-10-15.1").path))
        XCTAssertEqual(names, Set(copy.keys.map { "\($0).json" }), "exactly the new copy's files, none left from the bundle")
        let launch = files.choose(layout, build: 2, now: clock)
        let read = try layout.read(launch.folder)
        XCTAssertEqual(read.generated, "2026-10-15")
        XCTAssertEqual(read.places, OTAFixture.placeCount(copy))

        // a copy without the file that dates it is refused
        var headless = newer("2026-10-19")
        headless[layout.head] = nil
        headless["extra-notes"] = ["places": [] as [Any]]
        try publish(headless, version: "2026-10-19.1")
        let refused = await updater(using: launch).check(placesInUse: bundledPlaces)
        XCTAssertEqual(refused, .failed)
        XCTAssertEqual(files.current()?.version, "2026-10-15.1")
    }

    /// A detail file that belongs to other data (ids not in this places.json) is a mixed copy: refused.
    func testDetailFromOtherDataIsRejected() async throws {
        guard layout.kind == .coreDetail else { return }
        var copy = newer("2026-10-15")
        guard let name = copy.keys.filter({ $0.hasPrefix("detail-") && !(copy[$0] as! [String: Any]).isEmpty }).sorted().first else { return }
        var d = copy[name] as! [String: Any]
        d["zzzz00000000"] = d.values.first!
        copy[name] = d
        try publish(copy, version: "2026-10-15.1")
        let outcome = await updater().check(placesInUse: bundledPlaces)
        XCTAssertEqual(outcome, .failed)
    }

    // MARK: launch

    func testLaunchFallsBackToTheBundle() async throws {
        XCTAssertFalse(files.choose(layout, build: 2, now: clock).downloaded, "nothing downloaded")
        try publish(newer("2026-10-15"), version: "2026-10-15.1")
        _ = await updater().check(placesInUse: bundledPlaces)
        XCTAssertTrue(files.choose(layout, build: 2, now: clock).downloaded)

        // screenshot mode reads the bundle and leaves the download alone
        XCTAssertFalse(files.choose(layout, build: 2, now: clock, downloads: false).downloaded)
        XCTAssertNotNil(files.current())

        // a damaged file (same size, other bytes): the bundle, and the download is deleted
        let head = files.folder("2026-10-15.1").appending(path: "\(layout.head).json")
        var bytes = try Data(contentsOf: head)
        bytes[bytes.count / 2] ^= 0x01
        try bytes.write(to: head)
        let launch = files.choose(layout, build: 2, now: clock)
        XCTAssertFalse(launch.downloaded)
        XCTAssertEqual(launch.version, .bundled("2026-10-01"))
        XCTAssertFalse(FileManager.default.fileExists(atPath: files.root.path))

        // a copy checked by another build of the app (its loader may differ) isn't used
        _ = await updater().check(placesInUse: bundledPlaces, manual: true)
        XCTAssertTrue(files.choose(layout, build: 2, now: clock).downloaded)
        XCTAssertFalse(files.choose(layout, build: 3, now: clock).downloaded)
        XCTAssertNil(files.current())

        // an app update that ships newer data than the download deletes it
        _ = await updater().check(placesInUse: bundledPlaces, manual: true)
        try OTAFixture.write(OTAFixture.copy(generated: "2026-10-16"), to: bundle)
        XCTAssertFalse(files.choose(layout, build: 2, now: clock).downloaded)
        XCTAssertNil(files.current())
    }

    // MARK: the app itself

    /// The app's loader reads the copy AppData chose: the download's data, and (core + detail) its detail files.
    func testAppLoadsTheDownloadedCopy() async throws {
        let realSummary = try XCTUnwrap(Self.realSummary)
        let copy = newer(Self.dayAfter(realSummary.generated), rename: "Downloaded Place")
        try OTAFixture.write(copy, to: files.folder("x"))
        AppData.reset(DataCopy(version: DataVersion(date: Self.dayAfter(realSummary.generated), n: 1), folder: files.folder("x"), downloaded: true, files: [:]))
        let model = AppModel(defaults: defaults)
        await model.load()
        XCTAssertNil(model.loadError)
        XCTAssertTrue(model.isLoaded)
        XCTAssertEqual(model.generated, Self.dayAfter(realSummary.generated))
        XCTAssertEqual(model.places.count, OTAFixture.placeCount(copy))
        XCTAssertTrue(model.places.contains { $0.name == "Downloaded Place" })
    }

    /// A download this build's loader can't read: the app reads its bundled data instead, and the download is dropped.
    func testAppFallsBackWhenTheDownloadDoesntRead() async throws {
        var copy = newer("2030-01-01")
        copy[DataLayout.app.head] = OTAFixture.Raw(data: Data("{\"generated\":\"2030-01-01\",\"places\":[{".utf8))
        try OTAFixture.write(copy, to: files.folder("x"))
        AppData.reset(DataCopy(version: DataVersion(date: "2030-01-01", n: 1), folder: files.folder("x"), downloaded: true, files: [:]))
        let model = AppModel(defaults: defaults)
        await model.load()
        XCTAssertNil(model.loadError)
        XCTAssertTrue(model.isLoaded)
        XCTAssertEqual(model.generated, try XCTUnwrap(Self.realSummary).generated, "the bundled data")
        XCTAssertFalse(AppData.copy.downloaded, "and from now on")
        XCTAssertEqual(AppData.copy.folder, DataLayout.app.bundled)
    }

    func testDataAddressIsTheSitesOwn() {
        XCTAssertEqual(Links.appData.absoluteString, Links.site.absoluteString + "data/app/")
        XCTAssertEqual(Links.appData.scheme, "https")
        XCTAssertTrue(DataUpdater.allowsRedirect(to: URL(string: "https://nickstrom5.github.io/x/data/app/manifest.json"), from: Links.appData))
        XCTAssertTrue(DataUpdater.allowsRedirect(to: URL(string: "https://texas.eatsranked.com/data/app/manifest.json"), from: Links.appData))
        XCTAssertTrue(DataUpdater.allowsRedirect(to: Links.appData.appending(path: "manifest.json"), from: Links.appData))
        XCTAssertFalse(DataUpdater.allowsRedirect(to: URL(string: "http://texas.eatsranked.com/data/app/manifest.json"), from: Links.appData), "https only")
        XCTAssertFalse(DataUpdater.allowsRedirect(to: URL(string: "https://eatsranked.com.example.net/x"), from: Links.appData))
        XCTAssertFalse(DataUpdater.allowsRedirect(to: URL(string: "https://example.com/manifest.json"), from: Links.appData))
    }

    /// About and the privacy policy say how often the app contacts the site. If the schedule changes, the copy changes too.
    func testPrivacyNoteMatchesTheSchedule() {
        XCTAssertEqual(DataUpdater.checkEvery, 24 * 3600)
        XCTAssertEqual(DataUpdater.retryAfter, 3600)
        XCTAssertTrue(DataUpdater.privacyNote.contains("at most once a day") && DataUpdater.privacyNote.contains("an hour later"))
        XCTAssertTrue(DataUpdater.privacyNote.contains("no location or identifiers"))
        XCTAssertEqual(Set(DataUpdater.headers.keys), ["User-Agent", "Accept-Language"], "the only headers the app adds")
        XCTAssertFalse(DataUpdater.automaticChecks, "never during tests")
    }

    /// The app's real bundled data, read once with its own loader.
    static let realSummary = try? DataLayout.app.read(DataLayout.app.bundled)

    static func dayAfter(_ day: String) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(secondsFromGMT: 0)
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: DataVersion.day(day)!.addingTimeInterval(86400))
    }
}

/// Cut-down copies of this app's bundled data, in its own format: the head file dated as asked, a few places per places file,
/// and detail files cut to those places.
enum OTAFixture {
    /// Bytes to publish as they are (a broken file).
    struct Raw { let data: Data }

    static let keepPerFile = 60

    /// The bundled data files: name -> parsed JSON.
    static let source: [String: Any] = {
        let layout = DataLayout.app
        let names = (try? FileManager.default.contentsOfDirectory(atPath: layout.bundled.path)) ?? []
        var out: [String: Any] = [:]
        for n in names where n.hasSuffix(".json") {
            let name = String(n.dropLast(5))
            let ok: Bool
            switch layout.kind {
            case .single: ok = name == layout.head
            case .coreDetail: ok = name == layout.head || name.hasPrefix("detail-")
            case .regions: ok = DataManifest.validName(name)
            }
            if ok, let d = try? Data(contentsOf: layout.bundled.appending(path: n)), let j = try? JSONSerialization.jsonObject(with: d) { out[name] = j }
        }
        return out
    }()

    static func copy(generated: String) -> [String: Any] {
        var out: [String: Any] = [:], ids = Set<String>()
        for (name, obj) in source {
            guard var d = obj as? [String: Any] else { continue }
            if let places = d["places"] as? [[String: Any]] {
                let kept = Array(places.prefix(keepPerFile))
                ids.formUnion(kept.compactMap { $0["id"] as? String })
                d["places"] = kept
            }
            if name == DataLayout.app.head { d["generated"] = generated }
            out[name] = d
        }
        for (name, obj) in out where name.hasPrefix("detail-") {
            out[name] = (obj as! [String: Any]).filter { ids.contains($0.key) }
        }
        return out
    }

    /// The places in a copy's places files (an "extra-notes" file the app doesn't read doesn't count).
    static func placeCount(_ copy: [String: Any]) -> Int {
        var n = 0
        for (name, obj) in copy where name != "extra-notes" {
            if let places = (obj as? [String: Any])?["places"] as? [Any] { n += places.count }
        }
        return n
    }

    /// Rows as publish_app_data.py counts them: places in a file with places, ids in a detail file, 0 for an index.
    static func rows(_ name: String, _ obj: Any) -> Int {
        guard let d = obj as? [String: Any] else { return 0 }
        if let p = d["places"] as? [Any] { return p.count }
        return name.hasPrefix("detail-") ? d.count : 0
    }

    static func renameFirstPlace(_ copy: inout [String: Any], to newName: String) {
        let name = DataLayout.app.kind == .regions ? copy.keys.filter { $0 != DataLayout.app.head }.sorted().first! : DataLayout.app.head
        var d = copy[name] as! [String: Any]
        var places = d["places"] as! [[String: Any]]
        places[0]["n"] = newName
        d["places"] = places
        copy[name] = d
    }

    /// Regions: the index names `from` as `to` (wherever it names the file), and the file moves.
    static func renameRegionFile(_ copy: inout [String: Any], head: String, from: String, to: String) {
        copy[head] = replacingStrings(copy[head]!, "\(from).json", "\(to).json")
        copy[to] = copy[from]
        copy[from] = nil
    }

    /// Regions: the index entry naming `file` goes, and so does the file.
    static func dropRegionFile(_ copy: inout [String: Any], head: String, _ file: String) {
        copy[head] = dropping(copy[head]!, "\(file).json")
        copy[file] = nil
    }

    private static func replacingStrings(_ x: Any, _ a: String, _ b: String) -> Any {
        if let s = x as? String { return s == a ? b : s }
        if let l = x as? [Any] { return l.map { replacingStrings($0, a, b) } }
        if let d = x as? [String: Any] { return d.mapValues { replacingStrings($0, a, b) } }
        return x
    }

    /// Removes every object in a list that has `file` as one of its values.
    private static func dropping(_ x: Any, _ file: String) -> Any {
        if let l = x as? [Any] {
            return l.filter { !(($0 as? [String: Any])?.values.contains { ($0 as? String) == file } ?? false) }.map { dropping($0, file) }
        }
        if let d = x as? [String: Any] { return d.mapValues { dropping($0, file) } }
        return x
    }

    /// JSON with "generated" first, as the exporters write it (DataFiles.generatedDate reads only the start of a file).
    static func encode(_ obj: Any) throws -> Data {
        if let raw = obj as? Raw { return raw.data }
        guard var d = obj as? [String: Any], let g = d.removeValue(forKey: "generated") as? String else {
            return try JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys])
        }
        let rest = try JSONSerialization.data(withJSONObject: d, options: [.sortedKeys])
        var out = Data("{\"generated\":\"\(g)\"".utf8)
        if rest.count > 2 { out.append(Data(",".utf8)) }
        out.append(rest.dropFirst())
        return out
    }

    static func write(_ copy: [String: Any], to dir: URL) throws {
        if FileManager.default.fileExists(atPath: dir.path) { try FileManager.default.removeItem(at: dir) }
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        for (name, obj) in copy { try encode(obj).write(to: dir.appending(path: "\(name).json")) }
    }
}

/// A stand-in web server: serves what a test published, 404 for anything else, or fails every request as if offline.
final class OTAStub: URLProtocol {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var responses: [String: (status: Int, body: Data, headers: [String: String])] = [:]
    nonisolated(unsafe) private static var seen: [URLRequest] = []
    nonisolated(unsafe) private static var isOffline = false

    static func reset() { lock.withLock { responses = [:]; seen = []; isOffline = false } }
    static var offline: Bool {
        get { lock.withLock { isOffline } }
        set { lock.withLock { isOffline = newValue } }
    }
    static func serve(_ path: String, _ body: Data, status: Int = 200, headers: [String: String] = [:]) {
        lock.withLock { responses[path] = (status, body, headers) }
    }
    static var requests: [URLRequest] { lock.withLock { seen } }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let url = request.url!
        let (hit, offline) = Self.lock.withLock { () -> ((status: Int, body: Data, headers: [String: String])?, Bool) in
            Self.seen.append(request)
            return (Self.responses[url.path], Self.isOffline)
        }
        if offline {
            client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))
            return
        }
        let (status, body, headers) = hit ?? (404, Data(), [:])
        let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1",
                                       headerFields: headers.merging(["Content-Type": "application/json"]) { a, _ in a })!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
