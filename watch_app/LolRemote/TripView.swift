// « Rentrer » : trajet le plus court jusqu'à la maison (Shared/Journey.swift, IDFM
// temps réel), étape par étape ; « Guider » confie la marche à Plans (guidage pas à
// pas, tapotements au poignet). Ouvert depuis l'accueil ou par un appui sur la
// complication (lolremote://trip).
import MapKit
import SwiftUI
import WatchKit

struct TripView: View {
    @State private var location = LocationOnce()
    @State private var trip: Trip?
    @State private var status = "Recherche du trajet…"
    @State private var loading = false

    var body: some View {
        NavigationStack {
            List {
                if let trip {
                    Section {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Chez toi à \(clock(trip.arrival))").font(.system(size: 17, weight: .bold))
                            Text("\(trip.minutes) min · départ \(clock(trip.departure))")
                                .font(.system(size: 13)).foregroundStyle(Theme.muted)
                        }
                    }
                    Section {
                        ForEach(trip.steps, id: \.self) { step in StepRow(step: step) }
                    }
                } else {
                    Label(status, systemImage: loading ? "location" : "exclamationmark.triangle")
                        .font(.system(size: 14))
                }
                if Home.configured {
                    Button { guide() } label: {
                        Label("Guider (Plans)", systemImage: "location.north.line.fill")
                    }
                    .buttonStyle(PrimaryButtonStyle(height: 42))
                    .listRowBackground(Color.clear)
                    .doubleTapAction()
                }
            }
            .navigationTitle("Rentrer")
        }
        .task { await load() }
    }

    private func load() async {
        guard Home.configured else {
            status = "Domicile non configuré (secret HOME_COORDS)"
            return
        }
        location.requestPermission()
        loading = true
        defer { loading = false }
        guard let here = await location.current(maxAge: 60) else {
            trip = cachedTripHome()
            status = location.authorized ? "Position introuvable" : "Autorise la localisation (Réglages › Confidentialité)"
            return
        }
        if Home.isNear(here) {
            status = "Tu es chez toi"
            return
        }
        if let fresh = await fetchTripHome(from: here) {
            trip = fresh
        } else {
            trip = cachedTripHome()
            status = "Trajet indisponible (réseau ?)"
        }
    }

    /// Plans prend le relais : itinéraire en transports jusqu'à la maison.
    private func guide() {
        let item = MKMapItem(placemark: MKPlacemark(coordinate: Home.location.coordinate))
        item.name = "Maison"
        item.openInMaps(launchOptions: [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeTransit])
    }
}

private struct StepRow: View {
    let step: TripStep

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: icon).font(.system(size: 15)).foregroundStyle(Theme.accent).frame(width: 20)
            VStack(alignment: .leading, spacing: 1) {
                if step.transit {
                    Text("\([step.mode, step.line].filter { !$0.isEmpty }.joined(separator: " ")) · \(clock(step.departure))")
                        .font(.system(size: 15, weight: .semibold))
                    Text("\(step.from) → \(step.to)").font(.system(size: 12))
                    if !step.direction.isEmpty {
                        Text("direction \(step.direction)").font(.system(size: 11)).foregroundStyle(Theme.muted)
                    }
                } else {
                    Text("À pied · \(step.minutes) min").font(.system(size: 14, weight: .medium))
                    if !step.to.isEmpty {
                        Text("jusqu'à \(step.to)").font(.system(size: 12)).foregroundStyle(Theme.muted)
                    }
                }
            }
        }
    }

    private var icon: String {
        guard step.transit else { return "figure.walk" }
        switch step.mode.lowercased() {
        case let mode where mode.contains("bus"): return "bus.fill"
        case let mode where mode.contains("tram"): return "lightrail.fill"
        default: return "tram.fill"          // train, RER, métro
        }
    }
}

private let clockFormat: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "HH:mm"
    return f
}()

private func clock(_ date: Date) -> String { clockFormat.string(from: date) }
