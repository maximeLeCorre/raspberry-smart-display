// Complication / widget « Prochain train » (cadran et pile intelligente) :
// - CHEZ SOI (Pi joignable en Wi-Fi, ou à < 300 m) : prochains trains pour
//   St-Lazare, comme l'accueil du Pi (entrée en gare), lus sur le Pi
//   (GET /asset/transit/next). Un relevé (~1 h) donne une entrée par minute :
//   l'affichage avance seul jusqu'au relevé suivant (budget watchOS ~15-30 min).
// - AILLEURS : trajet le plus court pour rentrer (Shared/Journey.swift, IDFM) :
//   premier transport à prendre + heure d'arrivée ; un appui ouvre le détail.
// États toujours écrits (utilisateur daltonien).
import CoreLocation
import SwiftUI
import WidgetKit

struct Train: Codable, Hashable {
    let line: String
    let destination: String
    let time: Double                // départ attendu (epoch)
    let arrival: Double?            // entrée en gare attendue (epoch)
    let delay: Int                  // retard (min)
    let cancelled: Bool
    let platform: String?
    let toParis: Bool
    let home: Bool?                 // destination de l'accueil du Pi (St-Lazare)
    /// Heure affichée : entrée en gare si connue (comme le Pi), sinon départ.
    var date: Date { Date(timeIntervalSince1970: arrival ?? time) }
}

struct Board: Codable {
    let homeLabel: String?
    let updated: Double             // relevé PRIM du Pi (epoch, 0 = jamais)
    let departures: [Train]
}

enum WidgetContent {
    case trains(label: String, trains: [Train], updated: Date?)
    case trip(Trip)
    case none(String)               // message écrit (« Pi injoignable »…)
}

struct TrainEntry: TimelineEntry {
    let date: Date
    let content: WidgetContent
}

private let session = wifiSession(.ephemeral, timeout: 8)
private let cacheKey = "trainsBoard"

struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> TrainEntry { Self.sample }

    func getSnapshot(in context: Context, completion: @escaping (TrainEntry) -> Void) {
        if context.isPreview { return completion(Self.sample) }
        Task { completion(await Self.build().entries.first ?? Self.sample) }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TrainEntry>) -> Void) {
        Task {
            let built = await Self.build()
            completion(Timeline(entries: built.entries, policy: .after(Date().addingTimeInterval(built.refresh))))
        }
    }

    /// Chez soi → trains ; ailleurs → trajet ; et dans combien de temps recommencer.
    static func build() async -> (entries: [TrainEntry], refresh: TimeInterval) {
        if let board = await fetchBoard() {
            return (trainEntries(board), 15 * 60)                   // Wi-Fi de la maison
        }
        let cached = cachedBoard()
        guard HomePlace.configured else {
            return (cached.map(trainEntries) ?? [TrainEntry(date: Date(), content: .none("Pi injoignable"))], 15 * 60)
        }
        let here = await LocationOnce().current()
        if here == nil || HomePlace.isNear(here!) {
            let message = here == nil ? "Position inconnue" : "Pi injoignable"
            return (cached.map(trainEntries) ?? [TrainEntry(date: Date(), content: .none(message))], 15 * 60)
        }
        if let trip = await fetchTripHome(from: here!) ?? cachedTripHome() {
            return (tripEntries(trip), 10 * 60)
        }
        return ([TrainEntry(date: Date(), content: .none("Trajet indisponible"))], 10 * 60)
    }

    static func fetchBoard() async -> Board? {
        guard let result = try? await session.data(for: apiRequest("/asset/transit/next")),
              (result.1 as? HTTPURLResponse)?.statusCode == 200,
              let board = try? JSONDecoder().decode(Board.self, from: result.0) else { return nil }
        UserDefaults.standard.set(result.0, forKey: cacheKey)
        return board
    }

    static func cachedBoard() -> Board? {
        UserDefaults.standard.data(forKey: cacheKey).flatMap { try? JSONDecoder().decode(Board.self, from: $0) }
    }

    private static func minuteStart() -> Date {
        Date(timeIntervalSince1970: (Date().timeIntervalSince1970 / 60).rounded(.down) * 60)
    }

    /// Une entrée par minute tant qu'il reste des trains connus (90 min max).
    static func trainEntries(_ board: Board) -> [TrainEntry] {
        let updated = board.updated > 0 ? Date(timeIntervalSince1970: board.updated) : nil
        let label = board.homeLabel?.isEmpty == false ? board.homeLabel! : "Vers Paris"
        let mine = board.departures.filter { $0.home ?? $0.toParis }.sorted { $0.date < $1.date }
        var result: [TrainEntry] = []
        for minute in 0..<90 {
            let date = minuteStart().addingTimeInterval(Double(minute) * 60)
            let next = mine.filter { $0.date > date.addingTimeInterval(-30) }
            result.append(TrainEntry(date: date, content: .trains(label: label, trains: Array(next.prefix(3)),
                                                                  updated: updated)))
            if next.isEmpty { break }
        }
        return result
    }

    /// Une entrée par minute jusqu'au départ du 1er transport (le « dans X min » avance).
    static func tripEntries(_ trip: Trip) -> [TrainEntry] {
        let until = trip.firstTransit?.departure ?? trip.departure
        let count = max(1, min(30, Int(until.timeIntervalSince(minuteStart()) / 60) + 1))
        return (0..<count).map {
            TrainEntry(date: minuteStart().addingTimeInterval(Double($0) * 60), content: .trip(trip))
        }
    }

    static let sample = TrainEntry(date: Date(), content: .trains(label: "St-Lazare", trains: [
        Train(line: "L", destination: "Paris St-Lazare", time: Date().addingTimeInterval(300).timeIntervalSince1970,
              arrival: nil, delay: 0, cancelled: false, platform: "2", toParis: true, home: true),
        Train(line: "L", destination: "Paris St-Lazare", time: Date().addingTimeInterval(1200).timeIntervalSince1970,
              arrival: nil, delay: 3, cancelled: false, platform: "2", toParis: true, home: true),
    ], updated: Date()))
}

// MARK: - Textes

private let clockFormat: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "HH:mm"
    return f
}()

private func clock(_ date: Date) -> String { clockFormat.string(from: date) }

private func minutes(until date: Date, from now: Date) -> Int {
    max(0, Int((date.timeIntervalSince(now) / 60).rounded(.down)))
}

/// « 5 min », « à quai » ; « supprimé » écrit (jamais une simple couleur).
private func wait(_ train: Train, at date: Date) -> String {
    if train.cancelled { return "supprimé" }
    let left = minutes(until: train.date, from: date)
    return left == 0 ? "à quai" : "\(left) min"
}

private func delayText(_ train: Train) -> String {
    train.delay > 0 && !train.cancelled ? " +\(train.delay)" : ""
}

/// « Bus 171 », « Train L », « Métro 9 ».
private func lineName(_ step: TripStep) -> String {
    [step.mode, step.line].filter { !$0.isEmpty }.joined(separator: " ")
}

private func firstRunning(_ trains: [Train]) -> Train? {
    trains.first { !$0.cancelled } ?? trains.first
}

// MARK: - Vues

struct TrainsView: View {
    @Environment(\.widgetFamily) private var family
    let entry: TrainEntry

    var body: some View {
        content
            .widgetURL(URL(string: "lolremote://trip"))        // appui : détail dans l'app
    }

    @ViewBuilder private var content: some View {
        switch entry.content {
        case let .trains(label, trains, updated): trainsView(label, trains, updated)
        case let .trip(trip): tripView(trip)
        case let .none(message): noneView(message)
        }
    }

    // ----- Trains (chez soi)

    @ViewBuilder
    private func trainsView(_ label: String, _ trains: [Train], _ updated: Date?) -> some View {
        switch family {
        case .accessoryCircular:
            ZStack {
                AccessoryWidgetBackground()
                if let train = firstRunning(trains) {
                    VStack(spacing: -2) {
                        Text(train.line).font(.system(size: 11, weight: .heavy))
                        Text(train.cancelled ? "×" : "\(minutes(until: train.date, from: entry.date))")
                            .font(.system(size: 20, weight: .bold)).monospacedDigit()
                        Text(train.cancelled ? "suppr." : "min").font(.system(size: 10))
                    }
                } else {
                    Image(systemName: "tram")
                }
            }
            .containerBackground(for: .widget) { Color.clear }
        case .accessoryInline:
            Group {
                if let train = firstRunning(trains) {
                    Label("\(train.line) \(clock(train.date)) · \(wait(train, at: entry.date))\(delayText(train))",
                          systemImage: "tram.fill")
                } else {
                    Label("Pas de train", systemImage: "tram")
                }
            }
            .containerBackground(for: .widget) { Color.clear }
        case .accessoryCorner:
            Group {
                if let train = firstRunning(trains) {
                    Text(train.cancelled ? "×" : "\(minutes(until: train.date, from: entry.date))'")
                        .font(.system(size: 20, weight: .bold)).monospacedDigit()
                        .widgetLabel { Text("\(train.line) \(clock(train.date))\(delayText(train))") }
                } else {
                    Image(systemName: "tram").widgetLabel { Text("Pas de train") }
                }
            }
            .containerBackground(for: .widget) { Color.clear }
        default:
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 4) {
                    Image(systemName: "tram.fill")
                    Text(label).fontWeight(.semibold)
                    Spacer(minLength: 0)
                    // Relevé de plus de 20 min : retards peut-être dépassés.
                    if let updated, entry.date.timeIntervalSince(updated) > 20 * 60 {
                        Text("màj \(clock(updated))").foregroundStyle(.secondary)
                    }
                }
                .font(.system(size: 13))
                if trains.isEmpty {
                    Text("Aucun train prévu").font(.system(size: 14)).foregroundStyle(.secondary)
                }
                ForEach(trains.prefix(3), id: \.self) { train in
                    HStack(spacing: 5) {
                        Text(train.line).font(.system(size: 12, weight: .heavy))
                            .frame(width: 16, height: 16)
                            .background(.white.opacity(0.25), in: RoundedRectangle(cornerRadius: 4))
                        Text(clock(train.date))
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
    }

    // ----- Trajet retour (ailleurs)

    @ViewBuilder
    private func tripView(_ trip: Trip) -> some View {
        let first = trip.firstTransit
        switch family {
        case .accessoryCircular:
            ZStack {
                AccessoryWidgetBackground()
                VStack(spacing: -2) {
                    Image(systemName: "house.fill").font(.system(size: 10))
                    Text("\(minutes(until: trip.arrival, from: entry.date))")
                        .font(.system(size: 20, weight: .bold)).monospacedDigit()
                    Text("min").font(.system(size: 10))
                }
            }
            .containerBackground(for: .widget) { Color.clear }
        case .accessoryInline:
            Label(first.map { "\(lineName($0)) \(clock($0.departure)) · chez toi \(clock(trip.arrival))" }
                    ?? "À pied · chez toi \(clock(trip.arrival))",
                  systemImage: "house.fill")
                .containerBackground(for: .widget) { Color.clear }
        case .accessoryCorner:
            Text("\(minutes(until: trip.arrival, from: entry.date))'")
                .font(.system(size: 20, weight: .bold)).monospacedDigit()
                .widgetLabel { Text(first.map { "\(lineName($0)) \(clock($0.departure))" } ?? "à pied") }
                .containerBackground(for: .widget) { Color.clear }
        default:
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 4) {
                    Image(systemName: "house.fill")
                    Text("Chez toi \(clock(trip.arrival))").fontWeight(.semibold)
                    Spacer(minLength: 0)
                    Text("\(trip.minutes) min").foregroundStyle(.secondary)
                }
                .font(.system(size: 13))
                if let first {
                    Text("\(lineName(first)) · \(clock(first.departure))")
                        .font(.system(size: 15, weight: .semibold)).lineLimit(1).minimumScaleFactor(0.7)
                    let walk = trip.walkFirst
                    Text((walk > 0 ? "🚶 \(walk) min → " : "") + first.from)
                        .font(.system(size: 13)).lineLimit(1).minimumScaleFactor(0.7)
                } else {
                    Text("À pied").font(.system(size: 15, weight: .semibold))
                }
            }
            .widgetAccentable()
            .containerBackground(for: .widget) { Color(red: 0.11, green: 0.15, blue: 0.21) }
        }
    }

    private func noneView(_ message: String) -> some View {
        Label(message, systemImage: "tram")
            .font(.system(size: 13))
            .containerBackground(for: .widget) { Color.clear }
    }
}

@main
struct TrainsWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "Trains", provider: Provider()) { entry in
            TrainsView(entry: entry)
        }
        .configurationDisplayName("Prochain train")
        .description("Chez toi : trains pour St-Lazare. Ailleurs : le trajet pour rentrer.")
        .supportedFamilies([.accessoryRectangular, .accessoryCircular, .accessoryInline, .accessoryCorner])
    }
}
