import Foundation

/// Texas Eats' side of the data updates (OTA-DATA.md): places.json plus a detail file per region, checked with the loaders the app uses.
/// Every detail file must read and name only places in this places.json.
extension DataLayout {
    static let app = DataLayout(kind: .coreDetail, bundled: Bundle.main.resourceURL!, head: "places") { folder in
        let (file, places) = try AppModel.read(folder.appending(path: "places.json"))
        var rows = ["places": places.count]
        let ids = Set(places.map(\.id))
        for f in try FileManager.default.contentsOfDirectory(atPath: folder.path) where f.hasPrefix("detail-") && f.hasSuffix(".json") {
            let detail = try AppModel.readDetail(folder.appending(path: f))
            if let stray = detail.keys.first(where: { !ids.contains($0) }) { throw Mismatch(description: "\(f) names \(stray), not in places.json") }
            rows[String(f.dropLast(5))] = detail.count
        }
        return DataSummary(generated: file.generated, rows: rows, places: places.count)
    }
}
