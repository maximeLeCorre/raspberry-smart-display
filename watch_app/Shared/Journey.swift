// Trajet retour (hors de chez soi) : position de la montre → calculateur
// d'itinéraires d'IDFM (Navitia via PRIM, temps réel) → domicile. Partagé par
// l'app (TripView) et la complication. Appel DIRECT à Internet (pas le Pi : il
// n'est joignable que de la maison) : marche sans le Pi. Domicile saisi dans les
// Réglages, gardé dans l'App Group (partagé app ↔ complication) ; clé IDFM =
// Secrets (secret GitHub IDFM_API_KEY). Quota PRIM : 1 000 trajets / jour.
import CoreLocation
import Foundation

enum HomePlace {
    /// Groupe partagé app + complication (créé sur developer.apple.com, cf. README).
    static let group = "group.fr.maxime.lolremote"
    private static var defaults: UserDefaults { UserDefaults(suiteName: group) ?? .standard }

    static var label: String? { defaults.string(forKey: "homeLabel") }
    static var configured: Bool { !Secrets.idfmKey.isEmpty && defaults.object(forKey: "homeLat") != nil }
    static var location: CLLocation {
        CLLocation(latitude: defaults.double(forKey: "homeLat"), longitude: defaults.double(forKey: "homeLon"))
    }
    /// À moins de 300 m : chez soi (on affiche alors les trains, pas un trajet).
    static func isNear(_ here: CLLocation) -> Bool { here.distance(from: location) < 300 }

    static func setHome(lat: Double, lon: Double, label: String) {
        defaults.set(lat, forKey: "homeLat")
        defaults.set(lon, forKey: "homeLon")
        defaults.set(label, forKey: "homeLabel")
    }
}

struct TripStep: Codable, Hashable {
    let transit: Bool               // false = à pied
    let mode: String                // « Train », « Métro », « Bus »… (vide à pied)
    let line: String                // « L », « 171 »
    let direction: String
    let from: String
    let to: String
    let departure: Date
    let minutes: Int
}

struct Trip: Codable {
    let departure: Date
    let arrival: Date
    let steps: [TripStep]
    let fetched: Date

    var minutes: Int { Int((arrival.timeIntervalSince(departure) / 60).rounded()) }
    var firstTransit: TripStep? { steps.first(where: \.transit) }
    /// Marche avant le 1er transport (min).
    var walkFirst: Int { steps.prefix { !$0.transit }.reduce(0) { $0 + $1.minutes } }
}

// MARK: - Calculateur IDFM

private struct NavitiaResponse: Decodable {
    struct Journey: Decodable {
        let departure_date_time: String
        let arrival_date_time: String
        let sections: [Section]
    }
    struct Section: Decodable {
        struct Info: Decodable { let commercial_mode: String?; let code: String?; let direction: String? }
        struct Place: Decodable { let name: String? }
        let type: String
        let duration: Int?
        let departure_date_time: String?
        let display_informations: Info?
        let from: Place?
        let to: Place?
    }
    let journeys: [Journey]?
}

private let navitiaDate: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "yyyyMMdd'T'HHmmss"
    f.timeZone = TimeZone(identifier: "Europe/Paris")
    f.locale = Locale(identifier: "en_US_POSIX")
    return f
}()

/// « Gare (Ville) » → « Gare ».
private func placeName(_ name: String?) -> String {
    guard let name else { return "" }
    if let cut = name.range(of: " (", options: .backwards), name.hasSuffix(")") {
        return String(name[..<cut.lowerBound])
    }
    return name
}

/// Internet normal (relais de l'iPhone accepté) : rien à voir avec le Pi.
private let tripSession: URLSession = {
    let config = URLSessionConfiguration.ephemeral
    config.timeoutIntervalForRequest = 15
    return URLSession(configuration: config)
}()

private let tripCacheKey = "tripHome"

/// Meilleur trajet d'`here` à la maison (temps réel), sinon nil.
func fetchTripHome(from here: CLLocation) async -> Trip? {
    guard HomePlace.configured else { return nil }
    let home = HomePlace.location.coordinate
    var parts = URLComponents(string: "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia/journeys")!
    parts.queryItems = [
        URLQueryItem(name: "from", value: String(format: "%.5f;%.5f", here.coordinate.longitude, here.coordinate.latitude)),
        URLQueryItem(name: "to", value: String(format: "%.5f;%.5f", home.longitude, home.latitude)),
        URLQueryItem(name: "count", value: "1"),
        URLQueryItem(name: "max_nb_journeys", value: "1"),
        URLQueryItem(name: "data_freshness", value: "realtime"),
        URLQueryItem(name: "depth", value: "0"),
        URLQueryItem(name: "disable_geojson", value: "true"),
    ]
    var req = URLRequest(url: parts.url!)
    req.setValue(Secrets.idfmKey, forHTTPHeaderField: "apikey")
    guard let result = try? await tripSession.data(for: req),
          (result.1 as? HTTPURLResponse)?.statusCode == 200,
          let response = try? JSONDecoder().decode(NavitiaResponse.self, from: result.0),
          let journey = response.journeys?.first,
          let departure = navitiaDate.date(from: journey.departure_date_time),
          let arrival = navitiaDate.date(from: journey.arrival_date_time) else { return nil }
    let steps: [TripStep] = journey.sections.compactMap { section in
        let transit = section.type == "public_transport" || section.type == "on_demand_transport"
        let walk = ["street_network", "transfer", "crow_fly"].contains(section.type)
        let minutes = Int((Double(section.duration ?? 0) / 60).rounded())
        guard transit || (walk && minutes > 0) else { return nil }      // attentes : sautées
        let info = section.display_informations
        return TripStep(transit: transit, mode: transit ? (info?.commercial_mode ?? "") : "",
                        line: transit ? (info?.code ?? "") : "", direction: placeName(info?.direction),
                        from: placeName(section.from?.name), to: placeName(section.to?.name),
                        departure: section.departure_date_time.flatMap(navitiaDate.date(from:)) ?? departure,
                        minutes: minutes)
    }
    let trip = Trip(departure: departure, arrival: arrival, steps: steps, fetched: Date())
    UserDefaults.standard.set(try? JSONEncoder().encode(trip), forKey: tripCacheKey)
    return trip
}

/// Dernier trajet calculé (réseau indisponible), s'il n'est pas encore parti.
func cachedTripHome() -> Trip? {
    UserDefaults.standard.data(forKey: tripCacheKey)
        .flatMap { try? JSONDecoder().decode(Trip.self, from: $0) }
        .flatMap { $0.departure > Date().addingTimeInterval(-120) ? $0 : nil }
}

// MARK: - Position

/// Une position, une fois (précision ~100 m : assez pour un trajet, économe).
@MainActor
final class LocationOnce: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var continuation: CheckedContinuation<CLLocation?, Never>?

    var authorized: Bool {
        [.authorizedWhenInUse, .authorizedAlways].contains(manager.authorizationStatus)
    }

    /// L'app seule peut demander (une fois) ; la complication en profite ensuite.
    func requestPermission() {
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
    }

    func current(maxAge: TimeInterval = 300) async -> CLLocation? {
        if let known = manager.location, -known.timestamp.timeIntervalSinceNow < maxAge { return known }
        guard authorized else { return nil }
        return await withCheckedContinuation { continuation in
            self.continuation = continuation
            manager.delegate = self
            manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
            manager.requestLocation()
            Task {
                try? await Task.sleep(nanoseconds: 10_000_000_000)
                self.finish(self.manager.location)        // pas de réponse : dernière connue
            }
        }
    }

    private func finish(_ location: CLLocation?) {
        continuation?.resume(returning: location)
        continuation = nil
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        let last = locations.last
        Task { @MainActor in self.finish(last) }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in self.finish(self.manager.location) }
    }
}
