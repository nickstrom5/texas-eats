import SwiftUI
import UIKit
import CoreText

/// Texas flag palette (Nick's pick, 2026-10-20), light only: Old Glory blue #002868 (14.6:1 on white) for titles, tint and accents;
/// flag red #BF0A30 (6.4:1) for Texas guide cards and honors; white; a warm paper #F7F3EC behind the Home cards (butcher-paper pink
/// stays in the icon). No team colors: Texas's loyalties split. The names `green`/`gold` are kept from Wisconsin Eats so the shared
/// views read the same; here `green` is the flag blue and `gold` the flag red.
enum Theme {
    static let green = Color(hex: 0x002868)      // flag blue: titles, tint, primary text accents
    static let green2 = Color(hex: 0x1C3F86)
    static let gold = Color(hex: 0xBF0A30)       // flag red: card fills under white text, chips
    static let goldSoft = Color(hex: 0xF8DCE2)
    static let lime = Color(hex: 0xE7B9A6)       // butcher paper (the icon's), fills only
    static let limeSoft = Color(hex: 0xF6E7E0)
    static let sand = Color(hex: 0xF7F3EC)
    static let red = Color(hex: 0xBF0A30)        // MICHELIN chips and the cities' low bands only
    static let ink = Color(hex: 0x0E1A30)
    static let ink2 = Color(hex: 0x28385A)
    static let muted = Color(hex: 0x55627A)
    static let surface = Color.white
    static let surface2 = Color(hex: 0xF2F4F8)
    static let surface3 = Color(hex: 0xE1E6EF)
    static let rule = Color(hex: 0xDCE2EC)
    static let rule2 = Color(hex: 0xB5C0D3)
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }
}

/// A small uppercase label: "STONE CRAB", "1 MICHELIN STAR".
struct Chip: View {
    enum Style { case gold, green, red, plain, dashed }
    let text: String
    var style: Style = .plain

    var body: some View {
        Text(text.uppercased())
            .font(.caption2.weight(.bold))
            .tracking(0.4)
            .padding(.horizontal, 7).padding(.vertical, 3)
            .foregroundStyle(style == .green || style == .red ? Color.white : style == .dashed ? Theme.muted : style == .gold ? Theme.ink : Theme.green)
            .background {
                RoundedRectangle(cornerRadius: 5).fill(style == .gold ? Theme.goldSoft : style == .green ? Theme.green : style == .red ? Theme.red
                                                       : style == .dashed ? .clear : Theme.surface2)
            }
            .overlay {
                if style == .dashed { RoundedRectangle(cornerRadius: 5).strokeBorder(Theme.rule2, style: StrokeStyle(lineWidth: 1, dash: [3, 2])) }
            }
            .accessibilityLabel(text)
    }
}

/// A city's own inspection band or grade, as published: "Austin · Green", "El Paso · Passing", "Arlington · A". Texas has no
/// statewide grade and the app computes none.
struct BandBadge: View {
    let city: InspectionCity
    let band: InspectionBand
    var score: Int? = nil
    var large = false

    var body: some View {
        Text(([city.name, band.label] + (score.map { ["\($0)/100"] } ?? [])).joined(separator: " · ").uppercased())
            .font(large ? .footnote.weight(.heavy) : .caption2.weight(.heavy))
            .tracking(0.4)
            .multilineTextAlignment(.leading)
            .padding(.horizontal, large ? 10 : 7).padding(.vertical, large ? 6 : 3)
            .foregroundStyle(band.ink)
            .background(RoundedRectangle(cornerRadius: 6).fill(band.fill))
            .accessibilityLabel("\(city.name) inspection: \(band.label)" + (score.map { ", score \($0) out of 100" } ?? ""))
    }
}

/// Texas Eats' lettering: the system face drawn compressed and heavy for titles and guide names (like a roadhouse sign), and the
/// system monospaced face for numbers, dates and small labels. No bundled fonts.
struct DisplayFont: ViewModifier {
    let size: CGFloat
    var weight: Font.Weight = .black
    @ScaledMetric(relativeTo: .body) private var scale: CGFloat = 1

    func body(content: Content) -> some View {
        content.font(.system(size: size * min(scale, 1.6), weight: weight).width(.compressed))
    }
}

/// Numbers, dates and small labels in the system monospaced face, scaled like DisplayFont.
struct MonoFont: ViewModifier {
    let size: CGFloat
    var weight: Font.Weight = .semibold
    @ScaledMetric(relativeTo: .body) private var scale: CGFloat = 1

    func body(content: Content) -> some View {
        content.font(.system(size: size * min(scale, 1.6), weight: weight, design: .monospaced))
    }
}

extension View {
    func displayFont(_ size: CGFloat, weight: Font.Weight = .black) -> some View {
        modifier(DisplayFont(size: size, weight: weight))
    }

    func monoFont(_ size: CGFloat, weight: Font.Weight = .semibold) -> some View {
        modifier(MonoFont(size: size, weight: weight))
    }
}

/// The lone-star band under the Home title: the flag's blue, white and red laid flat, with one white star on the blue.
struct Stripes: View {
    var height: CGFloat = 6

    var body: some View {
        HStack(spacing: 0) {
            ZStack {
                Rectangle().fill(Theme.green)
                Image(systemName: "star.fill").font(.system(size: height * 2.2)).foregroundStyle(.white)
            }
            .frame(width: height * 6)
            VStack(spacing: 0) {
                Rectangle().fill(Theme.surface2)
                Rectangle().fill(Theme.red)
            }
        }
        .frame(height: height * 3.4)
        .clipShape(RoundedRectangle(cornerRadius: 3))
        .accessibilityHidden(true)
    }
}

extension View {
    /// An inline navigation title in the display type. UINavigationBar.appearance() didn't reach every SwiftUI bar on iOS 27
    /// (the Map title went from compressed blue to plain black after a push and pop; place titles were always plain), so the
    /// title is our own view in the bar. The navigation title is still set, for the back button and VoiceOver.
    func inlineTitle(_ title: String) -> some View {
        navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text(title).displayFont(19, weight: .heavy).foregroundStyle(Theme.green)
                        .lineLimit(1).minimumScaleFactor(0.7)
                        .accessibilityAddTraits(.isHeader)
                }
            }
    }
}
