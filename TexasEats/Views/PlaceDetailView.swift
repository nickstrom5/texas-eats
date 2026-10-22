import SwiftUI
import MapKit

struct PlaceDetailView: View {
    @Environment(AppModel.self) private var model
    @Environment(LocationService.self) private var location
    let place: Place

    @State private var mapItem: MKMapItem?
    @State private var lookingUp = false
    @State private var notOnAppleMaps = false
    @State private var appleMapsFailed = false
    /// inspection history, TABC licenses, reported alcohol sales, phone and website, from the place's region file (read when the place opens)
    @State private var detail: PlaceDetail?
    @State private var detailLoaded = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                actions
                if let c = place.coordinate { mapSnippet(c) }
                if place.handChecked && (place.note != nil || place.dishes != nil || place.founded != nil || place.seasonal != nil) { checked }
                if place.hasHonors { honors }
                if let i = place.inspection { inspections(i) }
                if let a = place.alcoholSalesK { alcohol(a) }
                records
                listing
            }
            .padding(16)
        }
        .background(Theme.surface)
        .inlineTitle(place.name)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                Button { model.toggleSaved(place) } label: {
                    Label(model.isSaved(place) ? "Saved" : "Save", systemImage: model.isSaved(place) ? "heart.fill" : "heart")
                }
                .accessibilityIdentifier("saveHeart")   // the Saved tab is also a "Saved" button
                ShareLink(item: shareText) { Label("Share", systemImage: "square.and.arrow.up") }
            }
        }
        .task(id: place.id) {
            detailLoaded = false
            detail = await model.detail(for: place)
            detailLoaded = true
        }
        .mapItemDetailSheet(item: $mapItem)
        .alert("Not on Apple Maps", isPresented: $notOnAppleMaps) {
            Button("Open Apple Maps anyway") { AppleMaps.openInMaps(place) }
            Button("OK", role: .cancel) {}
        } message: {
            Text("Apple Maps doesn't have a listing for \(place.name) at this spot, so there are no ratings or hours to show here.")
        }
        .alert("Couldn't reach Apple Maps", isPresented: $appleMapsFailed) {
            Button("Try again") { lookUp() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Check your connection and try again.")
        }
    }

    /// Apple's place card for this place; "not on Apple Maps" only when Apple answered and had no listing here.
    private func lookUp() {
        lookingUp = true
        Task {
            let result = await AppleMaps.findItem(for: place)
            lookingUp = false
            switch result {
            case .found(let item): mapItem = item
            case .notListed: notOnAppleMaps = true
            case .failed: appleMapsFailed = true
            }
        }
    }

    // MARK: sections

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            // "LOCKHART · CALDWELL COUNTY" (the data's county names already end in "County")
            Text((place.city ?? "Texas").uppercased() + (place.county.map { " · " + $0.uppercased() } ?? ""))
                .monoFont(12).tracking(0.4).foregroundStyle(Theme.green2)
            Text(place.name.uppercased())
                .displayFont(38).foregroundStyle(Theme.green)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
            Text([place.fullAddress, place.cuisine].filter { !$0.isEmpty }.joined(separator: " · "))
                .font(.subheadline).foregroundStyle(Theme.ink2)
                .textSelection(.enabled)
            if let here = model.screenshotLocation ?? location.location, let l = place.location {
                Text("\(here.milesText(to: l)) away").font(.subheadline).foregroundStyle(Theme.muted)
            }
            PlaceChips(place: place)
        }
    }

    private var actions: some View {
        VStack(spacing: 10) {
            Button { lookUp() } label: {
                HStack {
                    if lookingUp { ProgressView().tint(.white) } else { Image(systemName: "star.bubble") }
                    Text("Ratings, hours & photos").fontWeight(.semibold)
                    Spacer()
                    Text("Apple Maps").font(.caption).foregroundStyle(Theme.goldSoft)
                }
                .padding(14)
                .foregroundStyle(.white)
                .background(RoundedRectangle(cornerRadius: 12).fill(Theme.green))
            }
            .disabled(place.coordinate == nil || lookingUp)
            .accessibilityHint("Opens the Apple Maps place card with current ratings and hours")

            HStack(spacing: 10) {
                actionButton("Directions", "arrow.triangle.turn.up.right.diamond") { AppleMaps.openInMaps(place, directions: true) }
                if let phone = detail?.ph, let url = URL(string: "tel:\(phone.filter { $0.isNumber || $0 == "+" })") {
                    actionButton("Call", "phone") { UIApplication.shared.open(url) }
                }
                if let web = detail?.website {
                    actionButton("Website", "safari") { UIApplication.shared.open(web) }
                }
            }
        }
    }

    private func actionButton(_ title: String, _ icon: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: icon).font(.title3)
                Text(title).font(.caption.weight(.semibold))
            }
            .frame(maxWidth: .infinity, minHeight: 56)
            .foregroundStyle(Theme.green)
            .background(RoundedRectangle(cornerRadius: 12).strokeBorder(Theme.rule2))
        }
    }

    private func mapSnippet(_ c: CLLocationCoordinate2D) -> some View {
        Map(initialPosition: .region(MKCoordinateRegion(center: c, latitudinalMeters: 900, longitudinalMeters: 900)), interactionModes: []) {
            Marker(place.name, systemImage: place.tags.contains(.bbq) ? "flame.fill" : "fork.knife", coordinate: c).tint(Theme.green)
        }
        .frame(height: 170)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .onTapGesture { AppleMaps.openInMaps(place) }
        .accessibilityLabel("Map of \(place.name). Opens Apple Maps.")
        .accessibilityAddTraits(.isButton)
    }

    private var checked: some View {
        section("Hand-checked") {
            VStack(alignment: .leading, spacing: 8) {
                if let note = place.note { Text(note).font(.subheadline).foregroundStyle(Theme.ink2) }
                if let d = place.dishes { fact("On the menu", d.components(separatedBy: "; ").joined(separator: ", ")) }
                if let f = place.founded {
                    fact("Open here since", "\(f)")
                    // the note explains the year; without a year it only repeated the description above
                    if let fn = place.foundedNote { Text(fn).font(.caption).foregroundStyle(Theme.ink2) }
                }
                if let sea = place.seasonal { fact("Season", sea) }
                Text("Checked by hand against a 2025 or 2026 source: the place's own site or menu, local news or an official tourism listing. Menus and hours change, and many barbecue joints sell out early or open only a few days a week, so check before you go.")
                    .font(.caption).foregroundStyle(Theme.ink2)
            }
        }
    }

    private var honors: some View {
        section("Honors") {
            VStack(alignment: .leading, spacing: 8) {
                if let m = place.michelin.label {
                    Label(m + " · MICHELIN Guide Texas", systemImage: "rosette").font(.subheadline).foregroundStyle(Theme.ink)
                }
                ForEach(lines(place.jamesBeard, prefix: "James Beard: "), id: \.self) { l in
                    Label(l, systemImage: "rosette").font(.subheadline).foregroundStyle(Theme.ink)
                }
                Text("Honors are facts, not ratings. MICHELIN and the MICHELIN Guide are trademarks of Michelin; James Beard Foundation and James Beard Award are trademarks of the James Beard Foundation.")
                    .font(.caption).foregroundStyle(Theme.muted)
            }
        }
    }

    private func inspections(_ i: InspectionRecord) -> some View {
        section("Inspections · \(i.city.agency)") {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .center, spacing: 12) {
                    BandBadge(city: i.city, band: model.band(i.band), large: true)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(i.score)/100").monoFont(22).foregroundStyle(Theme.green)
                        Text("Latest inspection \(DayFormat.text(i.d) ?? i.d)").font(.subheadline).foregroundStyle(Theme.ink2)
                    }
                }
                if !detailLoaded { ProgressView().tint(Theme.green) }
                // by position: a routine inspection and its same-day follow-up are two entries
                ForEach(Array((detail?.inspection?.h ?? []).enumerated()), id: \.offset) { _, v in
                    HStack(alignment: .firstTextBaseline) {
                        Text(DayFormat.text(v.d) ?? v.d).font(.subheadline).monospacedDigit().foregroundStyle(Theme.ink2)
                        Text(model.visitType(v.t)).font(.subheadline).foregroundStyle(Theme.muted)
                        Spacer(minLength: 8)
                        Text("\(v.score)/100 · \(model.band(v.band).label)").font(.subheadline.weight(.semibold)).monospacedDigit().foregroundStyle(Theme.ink)
                    }
                }
                if let x = detail?.inspection, x.n > x.h.count {
                    Text("The latest \(x.h.count) of \(x.n) inspections in the last three years.").font(.caption).foregroundStyle(Theme.muted)
                }
                Text(i.city.scale + " Shown as \(i.city.name) published it; Texas has no statewide grade and this app computes none. One inspection is a snapshot of one day. Records through \(DayFormat.text(model.inspectionsThrough[i.city.key]) ?? "").")
                    .font(.caption).foregroundStyle(Theme.muted)
                Link(destination: i.city.sourceURL) {
                    Label("\(i.city.name)'s inspection records", systemImage: "arrow.up.right.square").font(.subheadline.weight(.semibold))
                }
                .foregroundStyle(Theme.green)
            }
        }
    }

    private func alcohol(_ k: Int) -> some View {
        section("Reported alcohol sales") {
            VStack(alignment: .leading, spacing: 8) {
                Text(GuideListView.money(k)).monoFont(22).foregroundStyle(Theme.green)
                let months = [model.alcoholFrom, model.alcoholTo].compactMap { DayFormat.monthYear($0.map { $0 + "-01" }) }
                Text("Liquor, wine, beer and cover charges the place's Mixed Beverage permit holder reported to the Texas Comptroller" + (months.count == 2 ? ", \(months[0]) through \(months[1])" : "") + ((detail?.aln).map { $0 < 12 ? " (\($0) months reported)" : "" } ?? "") + ". A reported figure, not our estimate.")
                    .font(.caption).foregroundStyle(Theme.muted)
                Link(destination: Links.mixbevData) {
                    Label("Mixed Beverage Gross Receipts (data.texas.gov)", systemImage: "arrow.up.right.square").font(.subheadline.weight(.semibold))
                }
                .foregroundStyle(Theme.green)
            }
        }
    }

    private var records: some View {
        section("Official records") {
            VStack(alignment: .leading, spacing: 8) {
                if let ls = detail?.licenses, !ls.isEmpty {
                    ForEach(ls, id: \.self) { l in
                        kv("TABC license " + Self.unbroken(l.id), l.type + (l.expires.flatMap { DayFormat.text($0) }.map { " · expires \($0)" } ?? ""))
                    }
                } else {
                    kv("Serves alcohol", detailLoaded ? "— (no TABC license matched)" : "…")
                }
                Text(recordsNote).font(.caption).foregroundStyle(Theme.muted)
                if detail?.licenses.isEmpty == false {
                    Link(destination: Links.tabcSearch) {
                        Label("Look up a license on TABC's site", systemImage: "arrow.up.right.square").font(.subheadline.weight(.semibold))
                    }
                    .foregroundStyle(Theme.green)
                }
            }
        }
    }

    private var listing: some View {
        section("How we know it's here") {
            VStack(alignment: .leading, spacing: 8) {
                kv("Listed as", place.tier.label)
                if place.tier == .licensed { kv("Official record", place.inspection.map { "\($0.city.name) inspections" } ?? "TABC licenses") }
                if place.chainCount >= 2 { kv("Locations in Texas", place.chainCount.formatted()) }
                Text(listingNote).font(.caption).foregroundStyle(Theme.muted)
            }
        }
    }

    /// "200034400", never broken across lines
    private static func unbroken(_ id: String) -> String { id.replacingOccurrences(of: "-", with: "\u{2011}") }

    /// Where the license comes from; a missing license is unknown, not "no alcohol".
    private var recordsNote: String {
        if detail?.licenses.isEmpty == false {
            return "From the Texas Alcoholic Beverage Commission's list of active licenses (data.texas.gov, read \(DayFormat.text(model.liquorUpdated) ?? model.liquorUpdated)). A Food and Beverage Certificate means food service is a real part of the business."
        }
        return "Texas has no statewide list of food licenses, so the only statewide record is TABC's alcohol licenses. No license matched this place: it may not serve alcohol, or it's licensed under another name, so a missing license means unknown, not no."
    }

    private var listingNote: String {
        let checked = place.handChecked
        if place.source == "research" {
            return "On our hand-checked list (checked against a 2025 or 2026 source). The open map data didn't list it as a place to eat, so it's placed from its own map listing or street address."
        }
        switch place.tier {
        case .licensed:
            return place.source == "official"
                ? "From an official list (a TABC license or a city's inspection list). The open map data didn't have it, so its location comes from the record's street address."
                : "Matched to an active TABC license or a city's inspection list."
        case .confirmed, .listing:
            let rate = model.matchRate(for: place)
            let base = place.tier == .confirmed
                ? "A high-confidence listing in Overture's open map data."
                : "A single listing in Overture's open map data, so it may be closed or misfiled."
            let measured = rate.map { " Checked against the establishments Austin, El Paso and Arlington inspect, listings like this matched an inspected or licensed business \($0) of the time." } ?? ""
            return base + measured + (checked ? " It's also on our hand-checked list, checked against a 2025 or 2026 source." : "")
        }
    }

    // MARK: helpers

    private var shareText: String {
        [place.name, place.fullAddress, "via Texas Eats", Links.site.absoluteString].filter { !$0.isEmpty }.joined(separator: "\n")
    }

    private func lines(_ s: String?, prefix: String) -> [String] {
        (s ?? "").components(separatedBy: "; ").filter { !$0.isEmpty }.map { prefix + $0 }
    }

    private func section<Content: View>(_ title: String, @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title.uppercased()).font(.caption.weight(.bold)).tracking(1).foregroundStyle(Theme.ink2)
            Divider()
            content()
        }
    }

    private func fact(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.ink)
            Text(value).font(.subheadline).foregroundStyle(Theme.ink2)
        }
    }

    @ViewBuilder
    private func kv(_ k: String, _ v: String?) -> some View {
        if let v {
            HStack(alignment: .firstTextBaseline) {
                Text(k).font(.subheadline).foregroundStyle(Theme.ink2)
                Spacer(minLength: 12)
                Text(v).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.ink).multilineTextAlignment(.trailing)
            }
        }
    }
}

extension String {
    var nonEmpty: String? { isEmpty ? nil : self }
}
