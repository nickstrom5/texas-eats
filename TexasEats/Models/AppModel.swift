import Foundation
import Observation
import CoreLocation

/// The whole app's state: the bundled places, filters, saved places and what's selected.
@MainActor
@Observable
final class AppModel {
    private(set) var places: [Place] = []
    private(set) var isLoaded = false
    private(set) var loadError: String?
    private(set) var generated = ""
    private(set) var restaurantCount = 0
    /// restaurants with a city inspection score (Austin, El Paso, Arlington only)
    var inspectedCount: Int { places.filter { !$0.isVenue && $0.inspection != nil }.count }
    private(set) var calibration = Calibration(areas: [:])
    /// the newest inspection in each city's records, by InspectionCity.key
    private(set) var inspectionsThrough: [String: String] = [:]
    /// the day TABC's license list was read
    private(set) var liquorUpdated = ""
    /// the months behind reported alcohol sales
    private(set) var alcoholFrom: String?
    private(set) var alcoholTo: String?
    /// the cities' own bands and grades, and their inspection types, verbatim
    private(set) var results: [String] = []
    private(set) var visitTypes: [String] = []
    /// the Overture Maps release the listings come from, read from the data file
    private(set) var overtureRelease: String?
    /// towns sorted by how many restaurants they have
    private(set) var towns: [(name: String, count: Int)] = []
    private(set) var cuisines: [(name: String, count: Int)] = []
    /// Bib Gourmand places (non-restaurants left out, like the other counts): the Filters switch shows only when there are some.
    private(set) var bibCount = 0
    /// normalized town name -> display name ("canon city" -> "Cañon City")
    private(set) var townKeys: [String: String] = [:]

    var filters = Filters() { didSet { saveFilters() } }
    private(set) var saved: Set<String> = []

    // navigation (iPad sidebar / iPhone tabs)
    var selectedGuide: Guide?
    var selectedPlace: Place?
    var tab: Tab = .guides
    enum Tab: Hashable { case guides, map, saved, about }
    /// the iPhone guides stack: a guide, then a place
    var guidesPath: [Route] = []
    enum Route: Hashable { case guide(Guide), place(Place) }
    /// bumped by openGuide so the iPad sidebar follows even when the same guide is picked again
    private(set) var guideRequest = 0
    /// iPad to iPhone-size (Split View, Stage Manager): the place that was open next to the Map or Saved list, for that tab's own
    /// stack to show, so a size-class change doesn't lose it
    var handoffPlace: Place?

    /// The iPhone guides stack for what's selected: the open guide, then the open place.
    var compactPath: [Route] {
        (selectedGuide.map { [Route.guide($0)] } ?? []) + (selectedPlace.map { [Route.place($0)] } ?? [])
    }

    /// iPhone: the stack changed (a push, a pop, a swipe back), so the selection follows it; an iPad layout then opens on the same
    /// guide and place.
    func followPath() {
        var guide: Guide?
        for r in guidesPath { if case .guide(let g) = r { guide = g } }
        if selectedGuide != guide { selectedGuide = guide }
        if case .place(let p) = guidesPath.last { if selectedPlace != p { selectedPlace = p } } else if selectedPlace != nil { selectedPlace = nil }
    }

    /// Open a guide from Home: pushes it on iPhone, selects it in the iPad sidebar.
    func openGuide(_ g: Guide) {
        tab = .guides
        selectedGuide = g
        guidesPath = [.guide(g)]
        guideRequest += 1
    }

    /// a fixed "you are here" for screenshots, so lists sort by distance without a permission prompt
    var screenshotLocation: CLLocation?

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        saved = Set(defaults.stringArray(forKey: "saved") ?? [])
        if let data = defaults.data(forKey: "filters"), let f = try? JSONDecoder().decode(Filters.self, from: data) { filters = f }
    }

    /// A cold launch from Spotlight asks for the data twice (the app's .task and the search continuation); both wait on one decode.
    private var loading: Task<Void, Never>?
    /// where a region's detail file is: the copy AppData chose (bundled or downloaded), or (tests) a folder next to a test core file
    private var detailURL: (String) -> URL? = { AppData.url("detail-" + $0) }
    /// region detail files already read, and the reads in flight (two places of one region opened quickly share one read)
    @ObservationIgnored private var details: [String: [String: PlaceDetail]] = [:]
    @ObservationIgnored private var detailLoads: [String: Task<[String: PlaceDetail], Never>] = [:]

    /// "Dallas–Fort Worth" -> "dallas-fort-worth": the file name the pipeline writes (detail-dallas-fort-worth.json)
    nonisolated static func regionSlug(_ region: String) -> String {
        region.lowercased().replacingOccurrences(of: "–", with: "-")
            .replacingOccurrences(of: "[^a-z]+", with: "-", options: .regularExpression).trimmingCharacters(in: CharacterSet(charactersIn: "-"))
    }

    /// The detail record for a place (inspection history, closures, license, phone, website), reading its region's file once.
    /// Nil when the place has no detail (no license, no phone, no inspections) or the file can't be read.
    func detail(for p: Place) async -> PlaceDetail? {
        let region = p.region ?? "Other"
        if let d = details[region] { return d[p.id] }
        if let t = detailLoads[region] { return await t.value[p.id] }
        let url = detailURL(Self.regionSlug(region))
        let t = Task.detached(priority: .userInitiated) { () -> [String: PlaceDetail] in
            guard let url else { return [:] }
            return (try? AppModel.readDetail(url)) ?? [:]
        }
        detailLoads[region] = t
        let d = await t.value
        details[region] = d
        detailLoads[region] = nil
        return d[p.id]
    }

    /// Reads a region's detail file: here, and in the check a downloaded copy passes (DataLayout.app).
    nonisolated static func readDetail(_ url: URL) throws -> [String: PlaceDetail] {
        try JSONDecoder().decode([String: PlaceDetail].self, from: Data(contentsOf: url))
    }

    func load(from url: URL? = AppData.url("places"), detailFolder: URL? = nil) async {
        if let detailFolder { detailURL = { detailFolder.appendingPathComponent("detail-\($0).json") } }
        guard !isLoaded else { return }
        if let loading { await loading.value; return }
        let task = Task { await decode(from: url) }
        loading = task
        await task.value
    }

    private func decode(from url: URL?) async {
        guard let url else { loadError = "The restaurant data is missing from the app."; return }
        do {
            let (file, places) = try await Task.detached(priority: .userInitiated) { try AppModel.read(url) }.value
            apply(file: file, places: places)
        } catch {
            // a downloaded copy this build can't read (OTA-DATA.md): back to the data built into the app
            if let bundled = AppData.fallback(from: url) { return await decode(from: bundled) }
            loadError = "The restaurant data couldn't be read (\(error.localizedDescription))."
        }
    }

    /// Reads a places.json: launch, and the check a downloaded copy passes before it's stored (DataLayout.app, OTA-DATA.md).
    nonisolated static func read(_ url: URL) throws -> (DataFile, [Place]) {
        let data = try Data(contentsOf: url)
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw DataFile.Malformed(field: "everything") }
        let file = try DataFile(json: root)
        // kept in A-to-Z order: a filter keeps it, so the A-to-Z sort of any list is a pass over an already sorted array
        let places = Place.build(root["places"] as? [[String: Any]] ?? [], file: file)
            .sorted { $0.sortKey != $1.sortKey ? $0.sortKey < $1.sortKey : $0.id < $1.id }
        return (file, places)
    }

    func apply(file: DataFile, places: [Place]) {
        self.places = places
        generated = file.generated
        restaurantCount = file.count_restaurants
        calibration = file.calibration
        inspectionsThrough = file.inspections_through
        liquorUpdated = file.liquor_updated
        alcoholFrom = file.mixbev_from
        alcoholTo = file.mixbev_to
        results = file.results
        visitTypes = file.itypes
        overtureRelease = file.overture_release
        var tc: [String: Int] = [:], cc: [String: Int] = [:]
        for p in places where !p.isVenue {
            if let c = p.city { tc[c, default: 0] += 1 }
            cc[p.cuisine, default: 0] += 1
        }
        towns = tc.map { ($0.key, $0.value) }.sorted { $0.count != $1.count ? $0.count > $1.count : $0.name < $1.name }
        cuisines = cc.map { ($0.key, $0.value) }.sorted { $0.count != $1.count ? $0.count > $1.count : $0.name < $1.name }
        bibCount = places.lazy.filter { !$0.isVenue && $0.michelin == .bib }.count
        var keys: [String: String] = [:]
        for (name, _) in towns {   // biggest town wins a shared spelling
            let k = Search.normalizeAddress(name)
            if keys[k] == nil { keys[k] = name }
        }
        townKeys = keys
        if let t = filters.town, tc[t] == nil { filters.town = nil }
        if let c = filters.cuisine, cc[c] == nil { filters.cuisine = nil }
        if filters.bibGourmand && bibCount == 0 { filters.bibGourmand = false }
        isLoaded = true
    }

    func place(id: String) -> Place? { places.first { $0.id == id } }

    /// The last list asked for. A list view's body runs on every change (an iPad row tap re-renders it), so the same guide, sort,
    /// search, filters and (for a distance sort) location to ~100 m reuse the result instead of filtering 17,000 places again.
    private struct ListKey: Equatable {
        let guide: Guide, sort: SortOrder, search: String, filters: Filters, count: Int, lat: Int?, lon: Int?
    }
    @ObservationIgnored private var lastList: (key: ListKey, places: [Place])?

    /// Places in a guide, filtered and searched, in the chosen order.
    func list(_ guide: Guide, sort: SortOrder, search: String, here: CLLocation?) -> [Place] {
        // reading filters and places here keeps SwiftUI observing them even when the cached list is returned
        let usesHere = sort == .nearest || guide == .nearMe
        let key = ListKey(guide: guide, sort: sort, search: search, filters: filters, count: places.count,
                          lat: usesHere ? here.map { Int(($0.coordinate.latitude * 1000).rounded()) } : nil,
                          lon: usesHere ? here.map { Int(($0.coordinate.longitude * 1000).rounded()) } : nil)
        if let lastList, lastList.key == key { return lastList.places }
        let out = makeList(guide, sort: sort, search: search, here: usesHere ? here : nil)
        lastList = (key, out)
        return out
    }

    private func makeList(_ guide: Guide, sort: SortOrder, search: String, here: CLLocation?) -> [Place] {
        let q = Search.parse(search, towns: townKeys)
        // typed something, but nothing searchable ("🍕", "!!!"): show nothing rather than everything
        if q.isEmpty && !search.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return [] }
        var out = places.filter { guide.includes($0) && filters.allows($0) && (q.isEmpty || Search.matches($0, q)) }
        if guide == .nearMe && here == nil { return [] }
        out = Ranking.sort(out, by: sort, from: here)
        if !q.tokens.isEmpty && !(guide.isRanked) {   // name matches first when searching
            let named = out.filter { Search.nameMatches($0, q) }
            if !named.isEmpty && named.count < out.count {
                let ids = Set(named.map(\.id))
                out = named + out.filter { !ids.contains($0.id) }
            }
        }
        return out
    }

    func count(_ guide: Guide) -> Int { places.lazy.filter { guide.includes($0) && self.filters.allows($0) }.count }

    // MARK: saved places

    func isSaved(_ p: Place) -> Bool { saved.contains(p.id) }

    func toggleSaved(_ p: Place) {
        if saved.contains(p.id) { saved.remove(p.id) } else { saved.insert(p.id) }
        defaults.set(Array(saved).sorted(), forKey: "saved")
    }

    var savedPlaces: [Place] { places.filter { saved.contains($0.id) }.sorted { $0.sortKey != $1.sortKey ? $0.sortKey < $1.sortKey : $0.id < $1.id } }

    /// A random place from a guide ("Surprise me"), never the one just shown.
    func randomPick(from guide: Guide, excluding last: String?) -> Place? {
        let pool = places.filter { guide.includes($0) && filters.allows($0) && $0.id != last }
        return pool.randomElement()
    }

    /// "Surprise me": a random hand-checked Texas pick (any guide), never the one just shown.
    func randomClassic(excluding last: String?) -> Place? {
        places.filter { $0.isClassic && filters.allows($0) && $0.id != last }.randomElement()
    }

    private func saveFilters() {
        if let data = try? JSONEncoder().encode(filters) { defaults.set(data, forKey: "filters") }
    }

    // MARK: honest labels

    /// "76%" (or "76–90%"): how often a listing of this kind matched an inspected or licensed business in Austin, El Paso County and
    /// Arlington, the three places where every food business is on a public list.
    func matchRate(for p: Place) -> String? {
        guard p.tier != .licensed else { return nil }   // an official record confirms it; no listing rate needed
        let group: String
        switch (p.source, p.tier) {
        case ("meta", .confirmed): group = "meta_high"
        case ("meta", _): group = "meta_mid"
        case ("AllThePlaces", _), ("DAC", _): group = "brand_feed"
        default: return nil
        }
        let v = calibration.areas.values.compactMap { $0.groups[group]?.official }.map { Int(($0 * 100).rounded()) }.sorted()
        guard let lo = v.first, let hi = v.last else { return nil }
        return lo == hi ? "\(lo)%" : "\(lo)–\(hi)%"
    }

    /// A city's band or grade label for an index in the data ("Green", "Passing", "A")
    func band(_ i: Int) -> InspectionBand { InspectionBand(index: i, label: i >= 0 && i < results.count ? results[i] : "") }
    func visitType(_ i: Int) -> String { i >= 0 && i < visitTypes.count ? visitTypes[i] : "" }
}
