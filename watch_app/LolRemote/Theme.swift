// Charte de l'app (maquettes : canvas « LolRemote – refonte montre ») : fond noir,
// accent bleu acier, cartes gris foncé. Action principale = grand bouton plein
// accent ; secondaire = gris. États toujours ÉCRITS + icône (utilisateur daltonien) :
// l'accent et le gris diffèrent aussi en clarté, pas seulement en teinte.
import SwiftUI

enum Theme {
    static let accent = Color(red: 0x8F / 255, green: 0xA9 / 255, blue: 0xC8 / 255)   // #8FA9C8
    static let ink = Color(red: 0x0E / 255, green: 0x15 / 255, blue: 0x20 / 255)      // texte sur l'accent
    static let card = Color(white: 0.11)          // #1C1C1E
    static let raised = Color(white: 0.17)        // #2C2C2E : boutons secondaires
    static let muted = Color(white: 0.63)         // #A1A1A6 : texte secondaire (contraste > 7:1)
}

/// Bouton principal : capsule pleine accent, toute la largeur.
struct PrimaryButtonStyle: ButtonStyle {
    var height: CGFloat = 50

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 17, weight: .bold))
            .foregroundStyle(Theme.ink)
            .frame(maxWidth: .infinity, minHeight: height)
            .background(Theme.accent, in: Capsule())
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

/// Bouton secondaire : capsule gris foncé, plus basse.
struct SecondaryButtonStyle: ButtonStyle {
    var height: CGFloat = 38

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 15, weight: .semibold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: height)
            .background(Theme.raised, in: Capsule())
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

/// En-tête d'écran : titre accent à gauche, info courte à droite.
struct ScreenHeader: View {
    let title: String
    var trailing: String = ""

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).font(.system(size: 15, weight: .semibold)).foregroundStyle(Theme.accent)
                .lineLimit(1).minimumScaleFactor(0.7)
            Spacer(minLength: 4)
            Text(trailing).font(.system(size: 12)).foregroundStyle(Theme.muted)
                .monospacedDigit().lineLimit(1)
        }
        .padding(.horizontal, 6)
    }
}

/// Anneau de compte à rebours (ready-check) ou de progression indéterminée.
struct CountdownRing: View {
    let fraction: Double      // part restante, 0…1
    let label: String
    var size: CGFloat = 78

    var body: some View {
        ZStack {
            Circle().stroke(Theme.raised, lineWidth: 7)
            Circle().trim(from: 0, to: max(0, min(1, fraction)))
                .stroke(Theme.accent, style: StrokeStyle(lineWidth: 7, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(.linear(duration: 1), value: fraction)
            Text(label).font(.system(size: size * 0.38, weight: .bold)).monospacedDigit()
        }
        .frame(width: size, height: size)
    }
}

/// Pastille ronde avec l'initiale d'un joueur.
struct Avatar: View {
    let name: String
    var size: CGFloat = 22

    var body: some View {
        Text(String(name.prefix(1)).uppercased())
            .font(.system(size: size * 0.5, weight: .bold))
            .frame(width: size, height: size)
            .background(Color(white: 0.23), in: Circle())
    }
}

extension View {
    /// Double tap (index + pouce, Series 9+ / Ultra 2, watchOS 11+) = appui sur ce
    /// bouton, sans toucher l'écran. UN seul par écran (l'action principale).
    @ViewBuilder func doubleTapAction() -> some View {
        if #available(watchOS 11.0, *) {
            handGestureShortcut(.primaryAction)
        } else {
            self
        }
    }
}
