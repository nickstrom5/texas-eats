import SwiftUI

struct FiltersSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var townSearch = ""

    var body: some View {
        @Bindable var model = model
        NavigationStack {
            Form {
                Section("Town") {
                    NavigationLink {
                        townPicker
                    } label: {
                        HStack {
                            Text("Town"); Spacer()
                            Text(model.filters.town ?? "All of Texas").foregroundStyle(Theme.muted)
                        }
                    }
                }
                Section("Cuisine") {
                    Picker("Cuisine", selection: $model.filters.cuisine) {
                        Text("All cuisines").tag(String?.none)
                        ForEach(model.cuisines, id: \.name) { c in Text("\(c.name) (\(c.count.formatted()))").tag(String?.some(c.name)) }
                    }
                }
                Section {
                    Toggle("Hide chains (5+ locations)", isOn: $model.filters.hideChains)
                    Toggle("Only licensed or confirmed places", isOn: $model.filters.confirmedOnly)
                    Toggle("Include non-restaurants", isOn: $model.filters.includeNonRestaurants)
                } footer: {
                    Text("Confirmed = on an active TABC license or a city's inspection list, a high-confidence map listing, or hand-checked by us. Non-restaurants are gas-station and grocery counters, stadium and airport stands, caterers, corporate cafeterias and delivery-only brands.")
                }
                // a fact from the MICHELIN Guide, not a rating; shown only when the data has Bib Gourmand places
                if model.bibCount > 0 {
                    Section("MICHELIN Guide") {
                        Toggle("Bib Gourmand (\(model.bibCount.formatted()))", isOn: $model.filters.bibGourmand)
                    }
                }
                if model.filters.activeCount > 0 {
                    Section { Button("Clear all filters", role: .destructive) { model.filters = Filters() } }
                }
            }
            .inlineTitle("Filters")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .presentationDetents([.medium, .large])
    }

    private var townPicker: some View {
        let q = Search.normalize(townSearch)
        let towns = model.towns.filter { q.isEmpty || (" " + Search.normalizeAddress($0.name)).contains(" " + Search.normalizeAddress(q)) }
        return List {
            Button { model.filters.town = nil } label: {
                HStack { Text("All of Texas"); Spacer(); if model.filters.town == nil { Image(systemName: "checkmark") } }
            }
            ForEach(towns, id: \.name) { t in
                Button { model.filters.town = t.name } label: {
                    HStack {
                        Text(t.name).foregroundStyle(Theme.ink)
                        Spacer()
                        Text(t.count.formatted()).foregroundStyle(Theme.muted).monospacedDigit()
                        if model.filters.town == t.name { Image(systemName: "checkmark").foregroundStyle(Theme.green) }
                    }
                }
            }
        }
        .searchable(text: $townSearch, prompt: "Find a town")
        .navigationTitle("Town")
    }
}
