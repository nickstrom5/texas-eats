import SwiftUI
import CoreLocation

struct GuideListView: View {
    @Environment(AppModel.self) private var model
    @Environment(LocationService.self) private var location
    let guide: Guide
    /// iPad passes a selection; iPhone pushes the place onto the stack
    var selection: Binding<Place?>? = nil

    @State private var sort: SortOrder?
    @State private var search = ""
    @State private var showFilters = false
    @State private var shown = 100

    /// Nearest first for the hand-checked guides when we know where you are in Texas; from out of state every row is hundreds of
    /// miles away, so the featured order reads better (Nearest is still in the sort menu). A sort that isn't one of this guide's
    /// options (left over from another guide) is ignored.
    private var order: SortOrder {
        if let sort, guide.sortOptions.contains(sort) { return sort }
        return guide.isTexas ? (here != nil && !outOfState ? .nearest : .featured) : guide.defaultSort
    }
    private var outOfState: Bool { model.screenshotLocation == nil && location.isOutsideTexas }
    private var here: CLLocation? { model.screenshotLocation ?? location.location }

    var body: some View {
        let places = model.list(guide, sort: order, search: search, here: here)
        List {
            Section {
                Text(guide.subtitle + (guide == .inspections ? inspectionsNote : guide == .alcohol ? alcoholNote : ""))
                    .font(.subheadline).foregroundStyle(Theme.muted)
                    .listRowSeparator(.hidden)
                if (order == .nearest || guide == .nearMe) && here == nil { locationPrompt }
                if order == .nearest && model.screenshotLocation == nil && location.isOutsideTexas {
                    Text("You're outside Texas. Every place here is in Texas, so distances are from where you are now.")
                        .font(.subheadline).foregroundStyle(Theme.ink2).listRowSeparator(.hidden)
                }
                if model.filters.activeCount > 0 { activeFilters }
            }
            Section {
                if places.isEmpty && !(guide == .nearMe && here == nil) {
                    ContentUnavailableView {
                        Label(search.isEmpty ? "Nothing here" : "No matches", systemImage: "magnifyingglass")
                    } description: {
                        Text(search.isEmpty ? "No places match your filters." : "No places match “\(search)” with your filters.")
                    } actions: {
                        if model.filters.activeCount > 0 { Button("Clear filters") { model.filters = Filters() } }
                        if !search.isEmpty { Button("Clear search") { search = "" } }
                    }
                }
                ForEach(Array(places.prefix(shown).enumerated()), id: \.element.id) { i, p in
                    row(p, rank: guide.isRanked ? i + 1 : nil)
                }
                if places.count > shown {
                    Button("Show more (\((places.count - shown).formatted()) left)") { shown += 200 }
                        .frame(maxWidth: .infinity).foregroundStyle(Theme.green)
                }
            } header: {
                Text("\(places.count.formatted()) \(places.count == 1 ? "place" : "places") · \(order.label)").textCase(nil).foregroundStyle(Theme.ink2)
            }
        }
        .listStyle(.plain)
        .navigationTitle(guide.title)
        .navigationBarTitleDisplayMode(.large)
        .searchable(text: $search, placement: .navigationBarDrawer(displayMode: guide == .all ? .always : .automatic), prompt: "Name, town, street or zip")
        .onChange(of: search) { shown = 100 }
        .onChange(of: sort) { shown = 100 }
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                if guide.sortOptions.count > 1 {
                    Menu {
                        Picker("Sort", selection: Binding(get: { order }, set: { sort = $0; if $0 == .nearest { location.request() } })) {
                            ForEach(guide.sortOptions) { Text($0.label).tag($0) }
                        }
                    } label: { Label("Sort", systemImage: "arrow.up.arrow.down") }
                }
                Button { showFilters = true } label: {
                    Label("Filters", systemImage: model.filters.activeCount > 0 ? "line.3.horizontal.decrease.circle.fill" : "line.3.horizontal.decrease.circle")
                }
            }
        }
        .sheet(isPresented: $showFilters) { FiltersSheet() }
        .task(id: guide) { if !ScreenshotMode.isActive && (guide == .nearMe || order == .nearest) { location.request() } }
    }

    /// The Inspections guide's explainer. The scores and bands are each city's own; the dates come from the data.
    private var inspectionsNote: String {
        let through = InspectionCity.allCases.compactMap { c in DayFormat.text(model.inspectionsThrough[c.key]).map { "\(c.name) \($0)" } }
        return ". Each place shows its latest score out of 100, as the city published it, with the city's own band: Austin's Green, Yellow or Red; El Paso's passing line of 70; Arlington's letter grade. Houston, Dallas, San Antonio and Fort Worth don't publish scores in bulk, and Texas has no statewide grade, so this app computes none. Records through " + through.joined(separator: ", ") + "."
    }

    /// The Bar Sales guide's explainer: a reported figure, with its months from the data.
    private var alcoholNote: String {
        let months = [model.alcoholFrom, model.alcoholTo].compactMap { DayFormat.monthYear($0.map { $0 + "-01" }) }
        return ". What each Mixed Beverage permit holder reported to the Texas Comptroller for liquor, wine, beer and cover charges" + (months.count == 2 ? ", \(months[0]) through \(months[1])" : "") + ". Places with only a beer-and-wine license don't report. Stadiums, hotels and arenas are hidden unless you include non-restaurants."
    }

    @ViewBuilder
    private func row(_ p: Place, rank: Int?) -> some View {
        let metric = metricText(p)
        let label = PlaceRow(place: p, rank: rank, rankLabel: rank.map(rankLabel), metric: metric, detail: detailLine(p), highlightTop: order != .lowestScore)
        if let selection {
            Button {
                selection.wrappedValue = p
                // iPad: the place opens beside the list, so put the search keyboard away (it covered half the place)
                UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
            } label: { label }
                .listRowBackground(selection.wrappedValue?.id == p.id ? Theme.surface2 : Theme.surface)
                .accessibilityAddTraits(selection.wrappedValue?.id == p.id ? .isSelected : [])
        } else {
            NavigationLink(value: AppModel.Route.place(p)) { label }
        }
    }

    /// "1st oldest": a place in a ranking, read as what the ranking is, not as a score
    private func rankLabel(_ rank: Int) -> String {
        let f = NumberFormatter()
        f.numberStyle = .ordinal
        let n = f.string(from: NSNumber(value: rank)) ?? "\(rank)"
        return guide == .oldest ? "\(n) oldest" : n
    }

    /// Inspection rows name the exact place and when it was inspected, so a result is never read without context.
    private func detailLine(_ p: Place) -> String? {
        guard guide == .inspections, let i = p.inspection else { return nil }
        let when = DayFormat.text(i.d).map { "inspected \($0)" } ?? "inspected \(i.d)"
        let away = order == .nearest ? here.flatMap { h in p.location.map { h.milesText(to: $0) + " away" } } : nil
        return [p.address, when, away].compactMap { $0 }.joined(separator: " · ")
    }

    private func metricText(_ p: Place) -> PlaceRow.Metric? {
        // an inspection row always shows its result, whatever the order (the distance goes in the detail line)
        if guide == .inspections, let i = p.inspection { return .result(i) }
        switch order {
        case .nearest: if let here, let l = p.location { return .text(here.milesText(to: l), "away") }
        case .oldest: if let f = p.founded { return .text("\(f)", "since") }
        case .iconic: return nil   // the chips say the honor; no points that could read like a rating
        case .recent, .highestScore, .lowestScore: if let i = p.inspection { return .result(i) }
        case .alcohol: if let a = p.alcoholSalesK { return .text(Self.money(a), "a year, reported") }
        default: break
        }
        if let f = p.founded, guide != .all { return .text("\(f)", "since") }
        return nil
    }

    /// "$1.2M", "$840K": reported sales in thousands of dollars
    static func money(_ k: Int) -> String {
        k >= 1000 ? "$" + (Double(k) / 1000).formatted(.number.precision(.fractionLength(1))) + "M" : "$\(k)K"
    }

    private var locationPrompt: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(location.isDenied ? "Location is off for this app. Turn it on in Settings to sort by distance."
                 : location.failed ? "Couldn't find your location. Check that Location Services is on, then try again."
                 : "Sort by distance from where you are. Your location stays on this device.")
                .font(.subheadline).foregroundStyle(Theme.ink2)
            if location.isDenied {
                Button("Open Settings") { LocationService.openSettings() }.buttonStyle(.bordered).tint(Theme.green)
            } else {
                Button(location.failed ? "Try again" : "Use my location") { location.request() }.buttonStyle(.borderedProminent).tint(Theme.green)
            }
        }
        .padding(.vertical, 4)
        .listRowSeparator(.hidden)
    }

    private var activeFilters: some View {
        HStack {
            Text("\(model.filters.activeCount) filter\(model.filters.activeCount == 1 ? "" : "s") on").font(.subheadline).foregroundStyle(Theme.ink2)
            Spacer()
            Button("Clear") { model.filters = Filters() }.font(.subheadline.weight(.semibold))
        }
        .listRowSeparator(.hidden)
    }
}

struct PlaceRow: View {
    @Environment(AppModel.self) private var model
    enum Metric { case text(String, String), result(InspectionRecord) }
    let place: Place
    var rank: Int?
    /// what VoiceOver says for the rank ("1st oldest")
    var rankLabel: String? = nil
    var metric: Metric?
    /// a second line under the town (inspections: street address and inspection date)
    var detail: String? = nil
    /// red for the top three of a ranking; never on the lowest-score sort
    var highlightTop = true

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            if let rank {
                Text("\(rank)")
                    .monoFont(rank < 100 ? 24 : 18)
                    .foregroundStyle(Theme.green)
                    .frame(minWidth: 38, minHeight: 38)
                    .background(RoundedRectangle(cornerRadius: 8).fill(rank <= 3 && highlightTop ? Theme.gold : .clear))
                    .accessibilityLabel(rankLabel ?? "Number \(rank)")
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(place.name).font(.body.weight(.semibold)).foregroundStyle(Theme.ink).multilineTextAlignment(.leading)
                Text(place.townLine).font(.subheadline).foregroundStyle(Theme.muted)
                if let detail { Text(detail).font(.caption).foregroundStyle(Theme.ink2) }
                PlaceChips(place: place, compact: true)
            }
            Spacer(minLength: 8)
            switch metric {
            case .text(let big, let small):
                VStack(alignment: .trailing, spacing: 0) {
                    Text(big).monoFont(20).foregroundStyle(Theme.green)
                    Text(small).font(.caption2).foregroundStyle(Theme.muted)
                }
            case .result(let i):
                VStack(alignment: .trailing, spacing: 3) {
                    BandBadge(city: i.city, band: model.band(i.band))
                    Text("\(i.score)/100").monoFont(16).foregroundStyle(Theme.green)
                        .accessibilityLabel("score \(i.score) out of 100")
                }
                .frame(maxWidth: 160, alignment: .trailing)
            case nil: EmptyView()
            }
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
    }
}

/// The small labels on a place: honors, the Texas guides, chain size, how sure we are it's real.
struct PlaceChips: View {
    let place: Place
    var compact = false

    var body: some View {
        let chips = items
        if !chips.isEmpty {
            FlowLayout(spacing: 5) {
                ForEach(chips, id: \.0) { Chip(text: $0.0, style: $0.1) }
            }
        }
    }

    private var items: [(String, Chip.Style)] {
        var out: [(String, Chip.Style)] = []
        if let m = place.michelin.label { out.append((m, .red)) }
        if let jb = place.jamesBeardChip { out.append((jb, .green)) }
        if place.handChecked {
            for (tag, label) in [(PlaceTags.bbq, "Barbecue"), (.texMex, "Tex-Mex"), (.taqueria, "Taquería"), (.kolache, "Kolaches"),
                                 (.chickenFried, "Chicken-fried steak")] where place.tags.contains(tag) {
                out.append((label, .gold))
            }
        }
        if place.tags.contains(.brewpub) { out.append(("Brewpub", .plain)) }
        if let f = place.founded, place.tags.contains(.oldest) { out.append(("Since \(f)", .plain)) }
        if place.isChain { out.append(("Chain · \(place.chainCount)", .plain)) }
        if place.tier == .listing && !place.isHonored && !place.handChecked { out.append(("Listing only", .dashed)) }
        return compact ? Array(out.prefix(4)) : out
    }
}

/// Wraps chips onto new lines. Each chip is offered the row's width, so one wider than the row (a long label at a large text
/// size on a small phone) wraps inside itself instead of being clipped. Measuring and placing share one arrangement, worked out
/// from the same proposal: placing by the (pixel-rounded) bounds once broke a row the measurement hadn't, and the row was cut off.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(proposal.width, subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let frames = arrange(proposal.width ?? bounds.width, subviews).frames
        for (v, f) in zip(subviews, frames) {
            v.place(at: CGPoint(x: bounds.minX + f.minX, y: bounds.minY + f.minY), proposal: ProposedViewSize(f.size))
        }
    }

    private func arrange(_ width: CGFloat?, _ subviews: Subviews) -> (frames: [CGRect], size: CGSize) {
        let maxW = width ?? .infinity
        var frames: [CGRect] = []
        var x: CGFloat = 0, y: CGFloat = 0, rowH: CGFloat = 0, widest: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(ProposedViewSize(width: width, height: nil))
            if x > 0 && x + s.width > maxW { y += rowH + spacing; x = 0; rowH = 0 }
            frames.append(CGRect(origin: CGPoint(x: x, y: y), size: s))
            x += s.width + spacing; rowH = max(rowH, s.height); widest = max(widest, x - spacing)
        }
        return (frames, CGSize(width: min(widest, maxW), height: y + rowH))
    }
}
