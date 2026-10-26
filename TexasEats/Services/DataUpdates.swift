import Foundation
import CryptoKit
import Observation
import SwiftUI

// Over-the-air data updates: ~/Developer/claudecode/OTA-DATA.md.
// This file is the same in every Eats Ranked state app. The app's own part is AppDataLayout.swift (DataLayout.app: where the
// bundled files are and how the app's loader reads a copy). Change state-prompts/ota/DataUpdates.swift and copy it to every
// app rather than editing one app's copy.

/// Which data a copy holds: its date (the head file's "generated", which the manifest calls records_through), then a same-day
/// counter for a republish ("2026-10-21.2"). The bundled copy counts as n = 0, below every published version of its date
/// (they start at 1), so a correction published for the same date reaches phones still on the bundled data. A published file
/// that's byte for byte one the phone already has is never downloaded (DataUpdater compares SHA-256).
struct DataVersion: Comparable, Sendable, CustomStringConvertible {
    let date: String          // yyyy-MM-dd, so strings compare in date order
    let n: Int

    static func bundled(_ date: String) -> DataVersion { DataVersion(date: date, n: 0) }

    init(date: String, n: Int) { self.date = date; self.n = n }

    /// "<date>.<n>", with the date matching `recordsThrough` and a real calendar day ("2026-99-99" and "2026-02-30" don't
    /// read back as themselves); nil for anything else. The string also names the download's folder, so nothing but a date
    /// and a number gets through.
    init?(_ version: String, recordsThrough: String) {
        guard version.wholeMatch(of: #/\d{4}-\d{2}-\d{2}\.\d{1,4}/#) != nil,
              let dot = version.lastIndex(of: "."), version[..<dot] == recordsThrough, Self.day(recordsThrough) != nil,
              let n = Int(version[version.index(after: dot)...]), n >= 1 else { return nil }
        self.init(date: recordsThrough, n: n)
    }

    var description: String { "\(date).\(n)" }

    /// Midnight UTC of a yyyy-MM-dd that is a real day, else nil.
    static func day(_ s: String) -> Date? {
        guard s.wholeMatch(of: #/\d{4}-\d{2}-\d{2}/#) != nil, let d = dayFormat.date(from: s), dayFormat.string(from: d) == s else { return nil }
        return d
    }

    /// Read in UTC: a day whose local midnight a clock change skips (Chile, 2026-09-06) would not parse in that time zone.
    private static let dayFormat: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(secondsFromGMT: 0)
        f.calendar = Calendar(identifier: .gregorian)
        f.dateFormat = "yyyy-MM-dd"
        f.isLenient = false
        return f
    }()

    /// The date is more than `days` days after `now`. A copy dated in the future would outrank every real publish and app
    /// update until that date, so the updater refuses one (3 days past the server's clock) and launch deletes a stored one
    /// (30 days past the device's).
    func isAhead(of now: Date, days: Double) -> Bool {
        guard let d = Self.day(date) else { return true }
        return d.timeIntervalSince(now) > days * 24 * 3600
    }

    static func < (a: DataVersion, b: DataVersion) -> Bool { (a.date, a.n) < (b.date, b.n) }
}

/// data/app/manifest.json on the state's site (scripts/publish_app_data.py writes it): which data files are current, with
/// their hashes, sizes and row counts. A file's key is its name in the app ("places" is places.json); its path is the
/// content-addressed copy next to the manifest ("places-1a2b3c4d5e6f.json").
struct DataManifest: Decodable, Equatable, Sendable {
    struct File: Decodable, Equatable, Sendable {
        let path: String
        let sha256: String
        let bytes: Int
        let rows: Int

        var wellFormed: Bool {
            path.wholeMatch(of: #/[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*\.json/#) != nil
                && sha256.lowercased().wholeMatch(of: #/[0-9a-f]{64}/#) != nil
                && (1...DataUpdater.maxFileBytes).contains(bytes) && rows >= 0
        }
    }

    let schema: Int
    let version: String
    let recordsThrough: String
    let minAppBuild: Int
    let files: [String: File]

    enum CodingKeys: String, CodingKey {
        case schema, version, files
        case recordsThrough = "records_through", minAppBuild = "min_app_build"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        schema = try c.decode(Int.self, forKey: .schema)
        version = try c.decode(String.self, forKey: .version)
        recordsThrough = try c.decode(String.self, forKey: .recordsThrough)
        minAppBuild = try c.decodeIfPresent(Int.self, forKey: .minAppBuild) ?? 1
        files = try c.decode([String: File].self, forKey: .files)
    }

    var dataVersion: DataVersion? { DataVersion(version, recordsThrough: recordsThrough) }

    /// A file's name in a copy's folder: lowercase words joined by hyphens ("places", "detail-keys", "places-la").
    static func validName(_ name: String) -> Bool { name.wholeMatch(of: #/[a-z0-9]+(-[a-z0-9]+)*/#) != nil }
}

/// What the app's own loader found in a copy: the data's date (the head file's "generated"), the rows of each file it read
/// (the counts publish_app_data.py writes in the manifest), and how many places the copy has.
struct DataSummary: Equatable, Sendable {
    var generated: String
    var rows: [String: Int]
    var places: Int
}

/// The app's side of an update, in AppDataLayout.swift: where the bundled files are, which file dates a copy, and how the
/// app's own loader reads a copy's folder (it throws unless every file the app uses reads).
struct DataLayout: Sendable {
    enum Kind: String, Sendable {
        case single          // places.json
        case regions         // Data/index.json + the region files it names
        case coreDetail      // places.json + detail-<region>.json
    }

    /// A copy whose files don't belong together (a detail file naming places the copy doesn't have).
    struct Mismatch: Error, CustomStringConvertible { let description: String }

    let kind: Kind
    let bundled: URL                                         // the folder holding the bundled files
    let head: String                                         // the file whose "generated" dates the copy
    let read: @Sendable (URL) throws -> DataSummary

    var bundledCopy: DataCopy {
        DataCopy(version: .bundled(DataFiles.generatedDate(bundled.appending(path: "\(head).json")) ?? ""), folder: bundled, downloaded: false, files: nil)
    }
}

/// A copy of the data: the bundled one, or a download in Application Support.
struct DataCopy: Equatable, Sendable {
    var version: DataVersion
    var folder: URL
    var downloaded: Bool
    var files: [String: String]?                             // a download's name -> SHA-256; nil for the bundle

    func url(_ name: String) -> URL { folder.appending(path: "\(name).json") }
}

/// Downloaded data on disk: <root>/<version>/<name>.json, and <root>/current.json naming the copy to use. Left out of iCloud
/// backup: it's public data the app can download again.
struct DataFiles: Sendable {
    let root: URL
    static let standard = DataFiles(root: URL.applicationSupportDirectory.appending(path: "AppData", directoryHint: .isDirectory))

    /// Our own record of the stored copy, written last when it's installed.
    struct Current: Codable, Equatable, Sendable {
        struct Stored: Codable, Equatable, Sendable { var sha256: String; var bytes: Int }
        var version: String
        var recordsThrough: String
        var build: Int                                       // the app build whose loader checked it
        var places: Int
        var files: [String: Stored]
        enum CodingKeys: String, CodingKey { case version, build, places, files; case recordsThrough = "records_through" }
    }

    var currentURL: URL { root.appending(path: "current.json") }
    func folder(_ version: String) -> URL { root.appending(path: version, directoryHint: .isDirectory) }

    func current() -> Current? {
        (try? Data(contentsOf: currentURL)).flatMap { try? JSONDecoder().decode(Current.self, from: $0) }
    }

    static func sha256(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }

    /// A file's SHA-256, read a megabyte at a time.
    static func sha256(file url: URL) throws -> String {
        let h = try FileHandle(forReadingFrom: url)
        defer { try? h.close() }
        var hasher = SHA256()
        while let chunk = try h.read(upToCount: 1 << 20), !chunk.isEmpty { hasher.update(data: chunk) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    static func size(_ url: URL) -> Int? {
        (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.intValue
    }

    /// The "generated" date near the top of a data file ({"v": "1", "generated": "2026-10-21", ...}), without parsing all of it.
    static func generatedDate(_ url: URL) -> String? {
        guard let h = try? FileHandle(forReadingFrom: url) else { return nil }
        defer { try? h.close() }
        guard let head = try? h.read(upToCount: 64 << 10) else { return nil }
        return String(decoding: head, as: UTF8.self).firstMatch(of: #/"generated"\s*:\s*"(\d{4}-\d{2}-\d{2})"/#).map { String($0.1) }
    }

    /// The copy to read this run: the download when it's newer than the bundle's data (a later date, or any published version
    /// of the same date), checked by this build of the app, not dated more than 30 days after `now`, and every file still
    /// exactly as checked; otherwise the bundle's, and the download is deleted. Leftovers (an older copy, an interrupted
    /// download) are removed. `downloads: false` (screenshot mode) reads the bundle and leaves any download where it is.
    func choose(_ layout: DataLayout, build: Int, now: Date = Date(), downloads: Bool = true) -> DataCopy {
        let bundled = layout.bundledCopy
        guard downloads else { return bundled }
        if let cur = current(), let v = DataVersion(cur.version, recordsThrough: cur.recordsThrough), v > bundled.version,
           cur.build == build, !v.isAhead(of: now, days: 30), cur.files[layout.head] != nil, intact(cur) {
            prune(keeping: [folder(cur.version)])
            return DataCopy(version: v, folder: folder(cur.version), downloaded: true, files: cur.files.mapValues(\.sha256))
        }
        removeAll()
        return bundled
    }

    /// Every file of the stored copy is there with its recorded size and hash.
    func intact(_ cur: Current) -> Bool {
        let dir = folder(cur.version)
        return cur.files.allSatisfy { name, f in
            let u = dir.appending(path: "\(name).json")
            return Self.size(u) == f.bytes && (try? Self.sha256(file: u)) == f.sha256
        }
    }

    /// The stored copy named by current.json, if its folder holds its files (sizes only: it was checked when it was stored).
    /// For the updater: a copy downloaded earlier in this run, or one this run doesn't read.
    func stored(_ layout: DataLayout) -> DataCopy? {
        guard let cur = current(), let v = DataVersion(cur.version, recordsThrough: cur.recordsThrough), cur.files[layout.head] != nil,
              cur.files.allSatisfy({ Self.size(folder(cur.version).appending(path: "\($0.key).json")) == $0.value.bytes }) else { return nil }
        return DataCopy(version: v, folder: folder(cur.version), downloaded: true, files: cur.files.mapValues(\.sha256))
    }

    /// A new, empty folder for a download in progress, next to the copies (so it moves into place in one step).
    func staging() throws -> URL {
        let fm = FileManager.default
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var r = root
        try r.setResourceValues(values)
        let dir = root.appending(path: ".incoming-\(UUID().uuidString)", directoryHint: .isDirectory)
        try fm.createDirectory(at: dir, withIntermediateDirectories: false)
        return dir
    }

    /// Moves a checked copy into place, then names it in current.json. Removes everything else but `keep` (the download
    /// this run is reading, whose files the app may still open).
    func install(_ staged: URL, as cur: Current, keep: URL?) throws {
        let fm = FileManager.default
        let dest = folder(cur.version)
        if fm.fileExists(atPath: dest.path) { try fm.removeItem(at: dest) }
        try fm.moveItem(at: staged, to: dest)
        try JSONEncoder().encode(cur).write(to: currentURL, options: .atomic)
        prune(keeping: [dest] + (keep.map { [$0] } ?? []))
    }

    /// Removes every copy and leftover but `keeping` and current.json.
    func prune(keeping: [URL]) {
        let keep = Set(keeping.map { $0.standardizedFileURL.path } + [currentURL.standardizedFileURL.path])
        for u in (try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
        where !keep.contains(u.standardizedFileURL.path) {
            try? FileManager.default.removeItem(at: u)
        }
    }

    func removeAll() {
        if FileManager.default.fileExists(atPath: root.path) { try? FileManager.default.removeItem(at: root) }
    }
}

/// The copy the app reads this run. The loaders take their files from here (AppData.url("places"), AppData.folder), so
/// every file comes from one copy: never a downloaded places.json with bundled detail files.
enum AppData {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var chosen: DataCopy?

    /// Chosen once, the first time it's asked for (AppData.prepare() does that off the main thread at launch).
    static var copy: DataCopy {
        lock.lock()
        defer { lock.unlock() }
        if let chosen { return chosen }
        let c = DataFiles.standard.choose(.app, build: DataUpdater.appBuild, downloads: DataUpdater.downloadsAllowed)
        chosen = c
        return c
    }

    static func url(_ name: String) -> URL { copy.url(name) }
    static var folder: URL { copy.folder }

    /// Chooses the copy (checking a download's hashes) before the loader asks, off the main thread.
    static func prepare() async {
        await Task.detached(priority: .userInitiated) { _ = copy }.value
    }

    /// A download the app's loader couldn't read (an app update can change the format): deletes it, reads the bundle from
    /// now on, and returns the bundle's copy of `url` (a file, or the copy's folder). Nil when `url` isn't the download in use.
    static func fallback(from url: URL?) -> URL? {
        guard let url else { return nil }
        lock.lock()
        defer { lock.unlock() }
        guard let c = chosen, c.downloaded else { return nil }
        let path = url.standardizedFileURL.path, dir = c.folder.standardizedFileURL.path
        guard path == dir || path.hasPrefix(dir + "/") else { return nil }
        let bundled = DataLayout.app.bundledCopy
        chosen = bundled
        DataFiles.standard.removeAll()
        return path == dir ? bundled.folder : bundled.folder.appending(path: String(path.dropFirst(dir.count + 1)))
    }

    /// Tests: forget the choice (or set one).
    static func reset(_ c: DataCopy? = nil) {
        lock.lock()
        chosen = c
        lock.unlock()
    }
}

/// When the app opens or comes back (at most once a day, or an hour after a failed try), checks the state's website for a
/// newer copy of the data, downloads the files that changed, checks every one (size, SHA-256, the app's own loader, the
/// date, the row counts, no big swing in the number of places) and stores the copy. The app reads it from its next launch;
/// nothing changes under a list someone is looking at. A failed update keeps the data in use and says nothing.
/// Nothing about the person is sent: no identifiers, no location, no cookies, no query, and a fixed Accept-Language.
@MainActor @Observable
final class DataUpdater {
    enum Outcome: Equatable, Sendable { case upToDate, downloaded(recordsThrough: String), failed }

    /// Content that failed a check. Automatic checks skip that version from then on, so a bad file isn't downloaded again
    /// and again; network errors aren't this and are retried.
    struct Rejected: Error, CustomStringConvertible { let reason: String; var description: String { reason } }

    nonisolated static let maxFileBytes = 48 << 20
    nonisolated static let maxTotalBytes = 160 << 20
    nonisolated static let maxFiles = 64
    nonisolated static let maxManifestBytes = 256 << 10
    nonisolated static let checkEvery: TimeInterval = 24 * 3600
    nonisolated static let retryAfter: TimeInterval = 3600
    /// A swing this big in the number of places is a pipeline bug, not two weeks of openings and closings.
    nonisolated static let maxSwing = 0.25

    /// What About and the privacy policy say about it. If the schedule changes, this has to change with it (a test checks).
    nonisolated static let privacyNote = "When you open the app, it checks our website for newer restaurant data, at most once a day (or an hour later if a check didn\u{2019}t go through), and downloads it when there is some; the app uses it the next time it opens. These requests carry no location or identifiers."

    /// The only headers the app adds: its name and version, and a fixed language, so the device's languages never go out.
    nonisolated static var headers: [String: String] {
        let info = Bundle.main.infoDictionary
        let name = (info?["CFBundleName"] as? String ?? "EatsRanked").filter { $0.isLetter || $0.isNumber }
        return ["User-Agent": "\(name)/\(info?["CFBundleShortVersionString"] as? String ?? "1.0")", "Accept-Language": "en"]
    }

    nonisolated static var appBuild: Int { Int(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "") ?? 0 }

    /// The data folder on the site, or in Debug builds `-dataBaseURL <url>` (a local server; compiled out of Release).
    nonisolated static var launchDataURL: URL {
        #if DEBUG
        let args = ProcessInfo.processInfo.arguments
        if let i = args.firstIndex(of: "-dataBaseURL"), i + 1 < args.count, let u = URL(string: args[i + 1]), u.scheme != nil { return u }
        #endif
        return Links.appData
    }

    /// Screenshot mode reads the bundled data (a leftover download could name other places).
    nonisolated static var downloadsAllowed: Bool { !ScreenshotMode.isActive }

    /// Off in screenshot mode and, in Debug builds, under unit tests (they run inside the app) and with -noDataUpdates
    /// (UI tests).
    nonisolated static var automaticChecks: Bool {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-noDataUpdates") || NSClassFromString("XCTestCase") != nil { return false }
        #endif
        return downloadsAllowed
    }

    /// Redirects go only to https on the site's own host, github.io or eatsranked.com (GitHub forwards github.io to the
    /// state's own domain once it has one).
    nonisolated static func allowsRedirect(to url: URL?, from site: URL) -> Bool {
        guard let url, url.scheme == "https", let host = url.host?.lowercased() else { return false }
        return host == site.host?.lowercased() || host == "nickstrom5.github.io" || host == "eatsranked.com" || host.hasSuffix(".eatsranked.com")
    }

    private(set) var lastCheck: Date?
    private(set) var checking = false
    /// The date of a newer copy that's downloaded and checked, waiting for the next launch.
    private(set) var waiting: String?

    @ObservationIgnored let dataURL: URL
    @ObservationIgnored let layout: DataLayout
    @ObservationIgnored let files: DataFiles
    /// The copy this run reads.
    @ObservationIgnored let inUse: () -> DataCopy
    @ObservationIgnored var automatic: Bool
    @ObservationIgnored private let session: URLSession
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let build: Int
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private var bundledShas: [String: String] = [:]

    private enum Key {
        static let lastCheck = "data.lastCheck", lastAttempt = "data.lastAttempt", rejected = "data.rejected"
    }

    init(dataURL: URL = DataUpdater.launchDataURL, layout: DataLayout = .app, files: DataFiles = .standard,
         inUse: @escaping () -> DataCopy = { AppData.copy }, configuration: URLSessionConfiguration = .ephemeral,
         defaults: UserDefaults = .standard, build: Int = DataUpdater.appBuild, automatic: Bool = DataUpdater.automaticChecks,
         now: @escaping () -> Date = Date.init) {
        self.dataURL = dataURL.absoluteString.hasSuffix("/") ? dataURL : URL(string: dataURL.absoluteString + "/")!
        self.layout = layout
        self.files = files
        self.inUse = inUse
        // ephemeral: no cookies, cache or credentials kept; the only headers we add are the app's name and a fixed language
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = 20
        configuration.timeoutIntervalForResource = 300
        configuration.httpAdditionalHeaders = Self.headers
        session = URLSession(configuration: configuration, delegate: RedirectGuard(site: dataURL), delegateQueue: nil)
        self.defaults = defaults
        self.build = build
        self.automatic = automatic
        self.now = now
        lastCheck = defaults.object(forKey: Key.lastCheck) as? Date
    }

    /// A GET for a file in the data folder, with no query and only our own headers (set on the request too, which wins over
    /// anything the system would add).
    private func request(_ path: String) -> URLRequest {
        var r = URLRequest(url: dataURL.appending(path: path))
        for (k, v) in Self.headers { r.setValue(v, forHTTPHeaderField: k) }
        return r
    }

    // MARK: when to check

    /// At most once a day, and an hour after a failed try. A clock set back doesn't stop checks for good.
    var isDue: Bool {
        func older(_ key: String, than seconds: TimeInterval) -> Bool {
            guard let d = defaults.object(forKey: key) as? Date else { return true }
            let age = now().timeIntervalSince(d)
            return age >= seconds || age < 0
        }
        return older(Key.lastCheck, than: Self.checkEvery) && older(Key.lastAttempt, than: Self.retryAfter)
    }

    /// After the first load and each time the app becomes active. `placesInUse`: how many places the app shows now.
    func checkIfDue(placesInUse: Int) {
        guard automatic, !checking, isDue, placesInUse > 0 else { return }
        Task { _ = await check(placesInUse: placesInUse) }
    }

    func phaseChanged(to phase: ScenePhase, placesInUse: Int?) {
        if phase == .active, let placesInUse { checkIfDue(placesInUse: placesInUse) }
    }

    // MARK: the check

    /// Checks the manifest against the newest copy on this phone (in use, or downloaded and waiting) and stores a newer one.
    /// `manual`: retry a version that was rejected before (tests; the app has no button for it).
    func check(placesInUse: Int, manual: Bool = false) async -> Outcome {
        guard !checking else { return .failed }
        checking = true
        defer { checking = false }
        defaults.set(now(), forKey: Key.lastAttempt)
        let using = inUse()
        let stored = files.stored(layout).flatMap { $0.version > using.version ? $0 : nil }
        let newest = stored ?? using
        do {
            let (m, served) = try await manifest()
            // a newer format, a newer app needed, or nothing newer: this app has the latest data it can use
            guard m.schema == 1, m.minAppBuild <= build, let v = m.dataVersion, v > newest.version else { return succeeded(.upToDate) }
            // the copy on hand already has exactly these files (a first publish of the data this build ships): nothing to get
            let have = await shas(of: newest, names: Array(m.files.keys))
            if m.files[layout.head] != nil, m.files.allSatisfy({ have[$0.key] == $0.value.sha256.lowercased() }) { return succeeded(.upToDate) }
            if !manual && m.version == defaults.string(forKey: Key.rejected) { return succeeded(.upToDate) }
            do {
                // records from the future: measured against the server's clock, so a phone's wrong clock doesn't matter; and
                // never past the 30 days launch allows on this phone's clock
                if v.isAhead(of: served ?? now(), days: 3) || v.isAhead(of: now(), days: 30) {
                    throw Rejected(reason: "records_through \(m.recordsThrough) is in the future")
                }
                try await download(m, placesInUse: placesInUse, sources: [newest, using], keep: using.downloaded ? using.folder : nil)
                defaults.removeObject(forKey: Key.rejected)
                waiting = m.recordsThrough
                return succeeded(.downloaded(recordsThrough: m.recordsThrough))
            } catch let e as Rejected {
                defaults.set(m.version, forKey: Key.rejected)
                print("Data update \(m.version) rejected: \(e.reason)")
                return .failed
            }
        } catch {
            return .failed
        }
    }

    private func succeeded(_ o: Outcome) -> Outcome {
        let t = now()
        defaults.set(t, forKey: Key.lastCheck)
        lastCheck = t
        return o
    }

    /// The manifest, and when the server sent it (its Date header), if it said.
    private func manifest() async throws -> (DataManifest, Date?) {
        let (data, response) = try await session.data(for: request("manifest.json"))
        guard let http = response as? HTTPURLResponse, http.statusCode == 200, data.count <= Self.maxManifestBytes else { throw URLError(.badServerResponse) }
        return (try JSONDecoder().decode(DataManifest.self, from: data), http.value(forHTTPHeaderField: "Date").flatMap(Self.httpDate.date(from:)))
    }

    /// An HTTP Date header: "Wed, 07 Oct 2026 19:16:00 GMT".
    nonisolated private static let httpDate: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(secondsFromGMT: 0)
        f.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
        return f
    }()

    /// The SHA-256 of a copy's files among `names`: a download's from its record, the bundle's worked out once, off the main
    /// thread, the first time a check needs them.
    private func shas(of copy: DataCopy, names: [String]) async -> [String: String] {
        if let f = copy.files { return f }
        let missing = names.filter { bundledShas[$0] == nil && DataManifest.validName($0) }
        if !missing.isEmpty {
            let folder = copy.folder
            let found = await Task.detached(priority: .utility) { () -> [String: String] in
                var out: [String: String] = [:]
                for name in missing { if let h = try? DataFiles.sha256(file: folder.appending(path: "\(name).json")) { out[name] = h } }
                return out
            }.value
            bundledShas.merge(found) { a, _ in a }
        }
        return bundledShas.filter { name, _ in FileManager.default.fileExists(atPath: copy.url(name).path) }
    }

    /// Gets every file of the manifest into a new folder (one already on this phone, in a copy on hand or the bundle, is
    /// copied instead of downloaded), checks the whole copy off the main thread and stores it.
    private func download(_ m: DataManifest, placesInUse: Int, sources: [DataCopy], keep: URL?) async throws {
        guard m.files.count <= Self.maxFiles, m.files[layout.head] != nil else { throw Rejected(reason: "no \(layout.head) in the manifest") }
        for (name, f) in m.files where !DataManifest.validName(name) || !f.wellFormed { throw Rejected(reason: "\(name): no usable manifest entry") }
        guard m.files.values.reduce(0, { $0 + $1.bytes }) <= Self.maxTotalBytes else { throw Rejected(reason: "too big") }
        var local: [String: URL] = [:]                    // SHA-256 -> a file with that content on this phone
        for copy in sources + [layout.bundledCopy] {
            for (name, sha) in await shas(of: copy, names: Array(m.files.keys)) where local[sha] == nil { local[sha] = copy.url(name) }
        }
        let staged = try files.staging()
        do {
            for (name, f) in m.files.sorted(by: { $0.key < $1.key }) {
                let dest = staged.appending(path: "\(name).json")
                if let src = local[f.sha256.lowercased()] {
                    try FileManager.default.copyItem(at: src, to: dest)
                } else {
                    try await fetch(f, to: dest)
                }
            }
            let layout = layout, build = build, files = files
            try await Task.detached(priority: .utility) {
                // every file exactly as the manifest says, a copied one too
                for (name, f) in m.files {
                    let u = staged.appending(path: "\(name).json")
                    guard DataFiles.size(u) == f.bytes, try DataFiles.sha256(file: u) == f.sha256.lowercased() else {
                        throw Rejected(reason: "\(name): size or SHA-256 doesn't match")
                    }
                }
                // a file with the right size and hash that the app can't read is bad content, like a hash mismatch
                let summary: DataSummary
                do { summary = try layout.read(staged) } catch { throw Rejected(reason: "doesn't read: \(error)") }
                try Self.validated(summary, manifest: m, head: layout.head, placesInUse: placesInUse)
                let cur = DataFiles.Current(version: m.version, recordsThrough: m.recordsThrough, build: build, places: summary.places,
                                            files: m.files.mapValues { .init(sha256: $0.sha256.lowercased(), bytes: $0.bytes) })
                try files.install(staged, as: cur, keep: keep)
            }.value
        } catch {
            try? FileManager.default.removeItem(at: staged)
            throw error
        }
    }

    /// One data file, refused unless it's exactly the size and hash the manifest gives.
    private func fetch(_ f: DataManifest.File, to dest: URL) async throws {
        var r = request(f.path)
        r.allowsConstrainedNetworkAccess = false             // Low Data Mode: wait for another network (the manifest is tiny)
        let (tmp, response) = try await session.download(for: r)
        defer { try? FileManager.default.removeItem(at: tmp) }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        // the size before reading it, so a huge file is never hashed or kept
        let size = DataFiles.size(tmp) ?? -1
        guard size == f.bytes, size <= Self.maxFileBytes else { throw Rejected(reason: "\(f.path): \(size) bytes, expected \(f.bytes)") }
        guard try DataFiles.sha256(file: tmp) == f.sha256.lowercased() else { throw Rejected(reason: "\(f.path): SHA-256 doesn't match") }
        try FileManager.default.moveItem(at: tmp, to: dest)
    }

    /// What the app's loader read must be what the manifest says, and close in size to the data in use.
    nonisolated static func validated(_ s: DataSummary, manifest m: DataManifest, head: String, placesInUse: Int) throws {
        guard s.generated == m.recordsThrough else { throw Rejected(reason: "generated \(s.generated), manifest \(m.recordsThrough)") }
        guard s.rows[head] != nil else { throw Rejected(reason: "\(head) wasn't read") }
        for (name, rows) in s.rows where m.files[name]?.rows != rows {
            throw Rejected(reason: "\(name): \(rows) rows, manifest \(m.files[name]?.rows ?? -1)")
        }
        guard placesInUse > 0, abs(Double(s.places - placesInUse)) <= Double(placesInUse) * maxSwing else {
            throw Rejected(reason: "\(s.places) places against \(placesInUse) in use")
        }
    }
}

/// Follows a redirect only to the hosts DataUpdater.allowsRedirect names.
private final class RedirectGuard: NSObject, URLSessionTaskDelegate, Sendable {
    let site: URL
    init(site: URL) { self.site = site }

    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest) async -> URLRequest? {
        DataUpdater.allowsRedirect(to: request.url, from: site) ? request : nil
    }
}

/// About's lines on data updates: how the app checks (the same words as the privacy policy), and a newer copy waiting for
/// the next launch. Works without a DataUpdater in the environment (previews, tests).
struct DataUpdatesNote: View {
    @Environment(DataUpdater.self) private var updater: DataUpdater?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(DataUpdater.privacyNote)
            if let d = updater?.waiting {
                Text("Newer data (\(Self.long(d))) is downloaded; the app uses it the next time it opens.")
            }
        }
    }

    /// "2026-10-21" -> "October 21, 2026".
    static func long(_ day: String) -> String {
        guard let d = DataVersion.day(day) else { return day }
        var style = Date.FormatStyle(date: .long, time: .omitted)
        style.timeZone = TimeZone(secondsFromGMT: 0)!
        return d.formatted(style)
    }
}
