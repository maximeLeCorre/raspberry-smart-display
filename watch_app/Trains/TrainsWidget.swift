// Complication / widget « Prochain train » (cadran et pile intelligente) : départs
// vers Paris de la gare du Pi (écran Trains, API PRIM), lus sur le Pi
// (GET /asset/transit/next). Un relevé (~1 h de départs) donne une entrée par
// minute : l'affichage avance seul, même sans réseau, jusqu'au relevé suivant
// (budget watchOS : ~ toutes les 15-30 min). Hors Wi-Fi de la maison, le dernier
// relevé reste affiché (« màj HH:MM »). États toujours écrits (utilisateur daltonien).
import SwiftUI
import WidgetKit

struct Train: Codable, Hashable {
    let line: String
    let destination: String
    let time: Double                // départ attendu (epoch)
    let delay: Int                  // retard (min)
    let cancelled: Bool
    let platform: String?
    let toParis: Bool
    var date: Date { Date(timeIntervalSince1970: time) }
}

struct Board: Codable {
    let updated: Double             // relevé PRIM du Pi (epoch, 0 = jamais)
    let departures: [Train]
}

struct TrainEntry: TimelineEntry {
    let date: Date
    let trains: [Train]             // prochains vers Paris, à partir de `date`
    let updated: Date?              // nil = aucun relevé
}

private let session = wifiSession(.ephemeral, timeout: 8)
private let cacheKey = "trainsBoard"

struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> TrainEntry { Self.sample }

    func getSnapshot(in context: Context, completion: @escaping (TrainEntry) -> Void) {
        if context.isPreview { return completion(Self.sample) }
        Task { completion(Self.entries(await Self.load()).first ?? Self.sample) }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TrainEntry>) -> Void) {
        Task {
            let entries = Self.entries(await Self.load())
            completion(Timeline(entries: entries, policy: .after(Date().addingTimeInterval(15 * 60))))
        }
    }

    /// Relevé du Pi (gardé en cache) ; Pi injoignable → dernier relevé connu.
    static func load() async -> Board? {
        if let result = try? await session.data(for: apiRequest("/asset/transit/next")),
           (result.1 as? HTTPURLResponse)?.statusCode == 200,
           let board = try? JSONDecoder().decode(Board.self, from: result.0) {
            UserDefaults.standard.set(result.0, forKey: cacheKey)
            return board
        }
        return UserDefaults.standard.data(forKey: cacheKey)
            .flatMap { try? JSONDecoder().decode(Board.self, from: $0) }
    }

    /// Une entrée par minute tant qu'il reste des trains connus (90 min max).
    static func entries(_ board: Board?) -> [TrainEntry] {
        let now = Date()
        let start = Date(timeIntervalSince1970: (now.timeIntervalSince1970 / 60).rounded(.down) * 60)
        guard let board else { return [TrainEntry(date: now, trains: [], updated: nil)] }
        let updated = board.updated > 0 ? Date(timeIntervalSince1970: board.updated) : nil
        let toParis = board.departures.filter(\.toParis).sorted { $0.time < $1.time }
        var result: [TrainEntry] = []
        for minute in 0..<90 {
            let date = start.addingTimeInterval(Double(minute) * 60)
            let next = toParis.filter { $0.date > date.addingTimeInterval(-30) }
            result.append(TrainEntry(date: date, trains: Array(next.prefix(3)), updated: updated))
            if next.isEmpty { break }
        }
        return result
    }

    static let sample = TrainEntry(date: Date(), trains: [
        Train(line: "L", destination: "Paris St-Lazare", time: Date().addingTimeInterval(300).timeIntervalSince1970,
              delay: 0, cancelled: false, platform: "2", toParis: true),
        Train(line: "U", destination: "La Défense", time: Date().addingTimeInterval(960).timeIntervalSince1970,
              delay: 3, cancelled: false, platform: "2", toParis: true),
    ], updated: Date())
}

// MARK: - Textes

private let clockFormat: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "HH:mm"
    return f
}()

/// « 5 min », « à quai » ; « supprimé » écrit (jamais une simple couleur).
private func wait(_ train: Train, at date: Date) -> String {
    if train.cancelled { return "supprimé" }
    let minutes = Int((train.date.timeIntervalSince(date) / 60).rounded(.down))
    return minutes <= 0 ? "à quai" : "\(minutes) min"
}

private func delayText(_ train: Train) -> String {
    train.delay > 0 && !train.cancelled ? " +\(train.delay)" : ""
}

/// Premier train non supprimé (petites complications : un seul train).
private func firstRunning(_ entry: TrainEntry) -> Train? {
    entry.trains.first { !$0.cancelled } ?? entry.trains.first
}

/// Relevé de plus de 20 min (hors Wi-Fi) : retards peut-être dépassés.
private func stale(_ entry: TrainEntry) -> Bool {
    guard let updated = entry.updated else { return false }
    return entry.date.timeIntervalSince(updated) > 20 * 60
}

// MARK: - Vues

struct TrainsView: View {
    @Environment(\.widgetFamily) private var family
    let entry: TrainEntry

    var body: some View {
        switch family {
        case .accessoryCircular: circular
        case .accessoryInline: inline
        case .accessoryCorner: corner
        default: rectangular
        }
    }

    /// Pile intelligente / grand emplacement : 2-3 trains.
    private var rectangular: some View {
        VStack(alignment: .leading, spacing: 1) {
            HStack(spacing: 4) {
                Image(systemName: "tram.fill")
                Text("Vers Paris").fontWeight(.semibold)
                Spacer(minLength: 0)
                if stale(entry), let updated = entry.updated {
                    Text("màj \(clockFormat.string(from: updated))").foregroundStyle(.secondary)
                }
            }
            .font(.system(size: 13))
            if entry.trains.isEmpty {
                Text(entry.updated == nil ? "Pi injoignable" : "Aucun train prévu")
                    .font(.system(size: 14)).foregroundStyle(.secondary)
            }
            ForEach(entry.trains.prefix(3), id: \.self) { train in
                HStack(spacing: 5) {
                    Text(train.line).font(.system(size: 12, weight: .heavy))
                        .frame(width: 16, height: 16)
                        .background(.white.opacity(0.25), in: RoundedRectangle(cornerRadius: 4))
                    Text(clockFormat.string(from: train.date))
                        .font(.system(size: 15, weight: .semibold)).monospacedDigit()
                        .strikethrough(train.cancelled)
                    Spacer(minLength: 0)
                    Text(wait(train, at: entry.date) + delayText(train))
                        .font(.system(size: 14)).monospacedDigit()
                }
            }
        }
        .widgetAccentable()
        .containerBackground(for: .widget) { Color(red: 0.11, green: 0.15, blue: 0.21) }
    }

    /// Rond : ligne + minutes.
    private var circular: some View {
        ZStack {
            AccessoryWidgetBackground()
            if let train = firstRunning(entry) {
                VStack(spacing: -2) {
                    Text(train.line).font(.system(size: 11, weight: .heavy))
                    Text(train.cancelled ? "×" : minutesOnly(train)).font(.system(size: 20, weight: .bold))
                        .monospacedDigit()
                    Text(train.cancelled ? "suppr." : "min").font(.system(size: 10))
                }
            } else {
                Image(systemName: "tram")
            }
        }
        .containerBackground(for: .widget) { Color.clear }
    }

    /// Une ligne de texte (au-dessus de l'heure sur certains cadrans).
    private var inline: some View {
        Group {
            if let train = firstRunning(entry) {
                Label("\(train.line) \(clockFormat.string(from: train.date)) · \(wait(train, at: entry.date))\(delayText(train))",
                      systemImage: "tram.fill")
            } else {
                Label("Pas de train", systemImage: "tram")
            }
        }
        .containerBackground(for: .widget) { Color.clear }
    }

    /// Coin : minutes au centre, ligne et heure le long du bord.
    private var corner: some View {
        Group {
            if let train = firstRunning(entry) {
                Text(train.cancelled ? "×" : "\(minutesOnly(train))'")
                    .font(.system(size: 20, weight: .bold)).monospacedDigit()
                    .widgetLabel { Text("\(train.line) \(clockFormat.string(from: train.date))\(delayText(train))") }
            } else {
                Image(systemName: "tram").widgetLabel { Text("Pas de train") }
            }
        }
        .containerBackground(for: .widget) { Color.clear }
    }

    private func minutesOnly(_ train: Train) -> String {
        "\(max(0, Int((train.date.timeIntervalSince(entry.date) / 60).rounded(.down))))"
    }
}

@main
struct TrainsWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "Trains", provider: Provider()) { entry in
            TrainsView(entry: entry)
        }
        .configurationDisplayName("Prochain train")
        .description("Départs vers Paris (lignes L et U), lus sur le Pi.")
        .supportedFamilies([.accessoryRectangular, .accessoryCircular, .accessoryInline, .accessoryCorner])
    }
}
