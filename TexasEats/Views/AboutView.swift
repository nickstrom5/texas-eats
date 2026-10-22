import SwiftUI

struct AboutView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 8) {
                    Text("TEXAS EATS").displayFont(32).foregroundStyle(Theme.green)
                    Text("A free guide to \(model.restaurantCount.formatted()) Texas restaurants, with hand-checked lists of barbecue joints, Tex-Mex, taquerías, kolache bakeries, chicken-fried steak and the state's oldest places, MICHELIN and James Beard honors, the alcohol sales the state publishes, and the inspection scores Austin, El Paso and Arlington publish. No account, no ads, no tracking.")
                        .font(.subheadline).foregroundStyle(Theme.ink2)
                    Text("Texas Eats (\u{201C}TX Eats\u{201D}) is an independent app by Nicholas Soderstrom. It is not affiliated with, endorsed by or operated by the State of Texas, the Texas Alcoholic Beverage Commission, the Texas Comptroller of Public Accounts, the Texas Department of State Health Services, the City of Austin, Austin Public Health, the City of El Paso, the City of Arlington, the MICHELIN Guide, the James Beard Foundation, Apple, or any restaurant or chain. Other names are trademarks of their owners.")
                        .font(.footnote).foregroundStyle(Theme.muted)
                }
                .padding(.vertical, 4)
            }
            Section("How the lists are built") {
                Text("The barbecue, Tex-Mex, taquería, kolache, chicken-fried steak and oldest-places lists are hand-checked: each place was checked against a 2025 or 2026 source (the place's own website or menu, local news or an official tourism listing), with the address checked. Founding years mean the year it opened at this address.")
                Text("Honors are the MICHELIN Guide Texas selection and James Beard Foundation awards and nominations from 2025 and 2026, plus America's Classics.")
                Text("Texas has no statewide list of restaurants. This app starts from open map listings (Overture Maps) and keeps the kinds that proved reliable: checked against the establishments Austin, El Paso County and Arlington inspect, high-confidence listings matched an inspected or licensed business \(rate("meta_high")) of the time. Active TABC licenses with on-premises alcohol, and the three cities' inspection lists, confirm places and add ones the map data missed, each placed on its street address. Adult clubs are left out. Website links are checked, and any that no longer belong to the place are left out.")
                Text("Inspection scores are each city's own: a score out of 100 with Austin's Green, Yellow or Red band, El Paso's passing line of 70, or Arlington's letter grade. Houston, Dallas, San Antonio and Fort Worth don't publish scores in bulk, and Texas has no statewide grade, so this app computes none.")
                Text("Reported alcohol sales are what each Mixed Beverage permit holder reports to the Texas Comptroller every month, summed over a year. They are reported figures, not estimates.")
                Text("Ratings, reviews, hours and photos are Apple Maps' own, shown live in Apple's place card. This app doesn't store or rank by them.")
            }
            .font(.subheadline).foregroundStyle(Theme.ink2)
            Section("Sources") {
                source("Texas Alcoholic Beverage Commission", "TABC License Information (data.texas.gov), active licenses read \(DayFormat.text(model.liquorUpdated) ?? model.liquorUpdated), modified for use in this app. For an official license status, use TABC's own public inquiry.", Links.tabcData.absoluteString)
                source("Texas Comptroller of Public Accounts", "Mixed Beverage Gross Receipts (data.texas.gov), the receipts each permit holder reports under Tax Code Chapter 183, \(model.alcoholFrom ?? "") to \(model.alcoholTo ?? "").", Links.mixbevData.absoluteString)
                source("Austin Public Health", "Food Establishment Inspection Scores (data.austintexas.gov, public domain), inspections of the last three years, through \(DayFormat.text(model.inspectionsThrough["aus"]) ?? "").", InspectionCity.austin.sourceURL.absoluteString)
                source("City of El Paso Department of Public Health", "Food Establishment Scores (foodscores.elpasotexas.gov), the city and the county towns it inspects, through \(DayFormat.text(model.inspectionsThrough["elp"]) ?? ""). The city says its scores are a summary only and doesn't guarantee their accuracy; full reports are available through its open-records system.", InspectionCity.elPaso.sourceURL.absoluteString)
                source("City of Arlington", "Food Establishments open data (opendata.arlingtontx.gov), the latest inspection of each establishment, through \(DayFormat.text(model.inspectionsThrough["arl"]) ?? "").", InspectionCity.arlington.sourceURL.absoluteString)
                source("Overture Maps Foundation", "Restaurant listings and websites come from Overture Maps Foundation places data (overturemaps.org)\(model.overtureRelease.map { ", release \($0)" } ?? ""), filtered and reformatted for this app.\n• Data from Meta, Microsoft, DAC and BrightQuery. Available under CDLA Permissive 2.0.\n• Data from Foursquare. \(foursquareCopyright) Available under Apache 2.0. Foursquare data was transformed to the Overture schema; this app further filtered and reformatted it. See the NOTICE below.\n• Data from AllThePlaces. Available under CC0 1.0.\nLicense records are placed on the map with Overture Maps addresses data (open address sources under permissive licenses, docs.overturemaps.org/attribution).", "https://overturemaps.org")
                source("U.S. Census Bureau Geocoder", "Puts license records on the map where Overture's address points don't reach. Public domain.", "https://geocoding.geo.census.gov")
                source("Honors", "The MICHELIN Guide Texas selection and James Beard Foundation awards, finalists and America's Classics are reported as facts and checked by hand against the official announcements. MICHELIN and the MICHELIN Guide are trademarks of Michelin. James Beard Foundation and James Beard Award are trademarks of the James Beard Foundation. Other names belong to their owners.", "https://guide.michelin.com/us/en/texas/restaurants")
                source("Maps", "Maps, place cards and directions by Apple Maps.", nil)
            }
            Section("Licenses") {
                NavigationLink("Community Data License Agreement – Permissive 2.0") { LicenseText(file: "CDLA-Permissive-2.0", title: "CDLA Permissive 2.0") }
                NavigationLink("Apache License 2.0") { LicenseText(file: "Apache-2.0", title: "Apache License 2.0") }
                NavigationLink("Foursquare OS Places NOTICE") { LicenseText(file: "Foursquare-NOTICE", title: "Foursquare NOTICE") }
            }
            Section("Privacy") {
                Text("The app collects nothing. Your location, if you allow it, only sorts lists by distance and shows where you are on the map, on this device. Saved places stay on this device.")
                    .font(.subheadline).foregroundStyle(Theme.ink2)
                Link("Privacy policy", destination: Links.privacy)
                Link("Terms of use", destination: Links.terms)
            }
            Section("Help") {
                Link("Report a missing or closed place", destination: Links.correctionEmail)
                Link("Email \(Links.supportEmail)", destination: URL(string: "mailto:\(Links.supportEmail)")!)
                Link("Website", destination: Links.site)
                Text("Data as of \(DayFormat.text(model.generated) ?? model.generated). Places open and close; check before you go. Version \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0")")
                    .font(.footnote).foregroundStyle(Theme.muted)
            }
        }
        .navigationTitle("About")
        .tint(Theme.green)
    }

    /// the copyright line exactly as the bundled Foursquare NOTICE has it, so the two can't disagree
    private var foursquareCopyright: String {
        guard let url = Bundle.main.url(forResource: "Foursquare-NOTICE", withExtension: "txt"),
              let text = try? String(contentsOf: url, encoding: .utf8),
              let line = text.split(separator: "\n").first(where: { $0.hasPrefix("©") }) else { return "© Foursquare Labs, Inc. All rights reserved." }
        return line.trimmingCharacters(in: .whitespaces)
    }

    private func rate(_ group: String) -> String {
        let v = model.calibration.areas.values.compactMap { $0.groups[group]?.official }.map { Int(($0 * 100).rounded()) }.sorted()
        guard let lo = v.first, let hi = v.last else { return "most" }
        return lo == hi ? "\(lo)%" : "\(lo)–\(hi)%"
    }

    @ViewBuilder
    private func source(_ name: String, _ detail: String, _ url: String?) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            if let url, let u = URL(string: url) { Link(name, destination: u).font(.subheadline.weight(.semibold)) }
            else { Text(name).font(.subheadline.weight(.semibold)) }
            Text(detail).font(.caption).foregroundStyle(Theme.muted)
        }
    }
}

/// A bundled license text (Resources/Licenses), reflowed rather than shown as raw 80-column lines.
struct LicenseText: View {
    let file: String
    let title: String

    var body: some View {
        ScrollView {
            Text(text).font(.footnote).foregroundStyle(Theme.ink).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading).padding()
        }
        .inlineTitle(title)
    }

    private var text: String {
        guard let url = Bundle.main.url(forResource: file, withExtension: "txt"),
              let raw = try? String(contentsOf: url, encoding: .utf8) else { return "License text missing." }
        // join hard-wrapped lines into paragraphs; keep blank lines and list items as breaks
        var out: [String] = []
        for para in raw.components(separatedBy: "\n\n") {
            let lines = para.components(separatedBy: "\n").map { $0.trimmingCharacters(in: .whitespaces) }
            var joined = ""
            for l in lines where !l.isEmpty {
                let startsItem = l.hasPrefix("–") || l.hasPrefix("-") || l.range(of: #"^\(?[a-z0-9]{1,3}[.)]\s"#, options: .regularExpression) != nil
                joined += joined.isEmpty ? l : (startsItem ? "\n" + l : " " + l)
            }
            if !joined.isEmpty { out.append(joined) }
        }
        return out.joined(separator: "\n\n")
    }
}
