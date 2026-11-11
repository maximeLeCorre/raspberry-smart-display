// Message privé du client League : réponse (réponses rapides directement dans la
// notification, ou « Répondre… » qui ouvre cet écran) ou nouveau message à un ami
// (fiche ami). Dictée en tête (gribouillage / clavier aussi), texte RELU avant
// l'envoi (la dictée se trompe sur les noms de jeu), puis phrases toutes faites. Envoi : action `chat_reply` du Pi → agent →
// LCU. (Pas de champ de texte DANS la notification : indisponible sur watchOS.)
import SwiftUI
import UserNotifications
import WatchKit

enum QuickReplies {
    static let all = ["J'arrive !", "2 min", "Pas dispo", "Ok 👍"]
    static let inNotification = 3          // les premières, en boutons de notification
    /// Pour écrire en premier à un ami (fiche ami).
    static let starters = ["On se fait une ARAM ?", "Je lance dans 5 min", "Tu finis bientôt ?"]
}

struct ReplyTarget: Identifiable {
    let conversationId: String      // = id (pid) de l'ami pour un nouveau message
    let from: String
    var starters = false            // nouveau message : phrases d'ouverture
    var id: String { conversationId }
}

/// Conversation à laquelle répondre (posée par « Répondre… » d'une notification).
@MainActor
final class ReplyCenter: ObservableObject {
    static let shared = ReplyCenter()
    @Published var target: ReplyTarget?
}

/// Envoie la réponse ; true si le Pi l'a prise en charge.
func sendReply(_ text: String, to conversationId: String) async -> Bool {
    await postToPi("/action", ["action": "chat_reply", "conversationId": conversationId,
                               "body": text]) == 200
}

/// Échec d'une réponse envoyée depuis la notification (app fermée) : on le dit.
func notifyReplyFailed(to from: String) {
    let content = UNMutableNotificationContent()
    content.title = "Réponse non envoyée"
    content.body = from.isEmpty ? "PC ou Pi injoignable" : "À \(from) : PC ou Pi injoignable"
    UNUserNotificationCenter.current().add(
        UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
}

struct ReplyView: View {
    let target: ReplyTarget
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var draft: String?       // texte dicté, à relire avant l'envoi
    @State private var sending = false
    @State private var failed = false

    var body: some View {
        NavigationStack {
            List {
                if let draft {
                    Section {
                        Text(draft).font(.system(size: 15))
                        Button { send(draft) } label: { Label("Envoyer", systemImage: "paperplane.fill") }
                            .foregroundStyle(Theme.accent)
                        Button { self.draft = nil; text = "" } label: { Label("Redicter", systemImage: "mic.fill") }
                    } footer: {
                        status(idle: "Dicté : vérifie avant d'envoyer.")
                    }
                } else {
                    // Dictée en tête : le champ ouvre la saisie de watchOS (micro, gribouillage,
                    // clavier) ; une app ne peut pas lancer la dictée elle-même. « OK » = relecture.
                    Section {
                        TextField(text: $text) {
                            Label("Dicter un message", systemImage: "mic.fill")
                        }
                        .onSubmit {
                            let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
                            if !body.isEmpty { draft = body }
                        }
                    } footer: {
                        status(idle: "Touche, puis le micro. Tu relis avant l'envoi.")
                    }
                    Section(target.starters ? "Messages rapides" : "Réponses rapides") {
                        ForEach(target.starters ? QuickReplies.starters : QuickReplies.all, id: \.self) { reply in
                            Button(reply) { send(reply) }
                        }
                    }
                }
            }
            .disabled(sending)
            .navigationTitle(target.from.isEmpty ? "Répondre" : "À \(target.from)")
        }
    }

    @ViewBuilder private func status(idle: String) -> some View {
        if failed {
            Label("Non envoyé : PC ou Pi injoignable", systemImage: "exclamationmark.triangle.fill")
        } else if sending {
            Label("Envoi…", systemImage: "paperplane")
        } else {
            Text(idle)
        }
    }

    private func send(_ reply: String) {
        let body = reply.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty else { return }
        sending = true
        failed = false
        Task {
            let ok = await sendReply(body, to: target.conversationId)
            sending = false
            if ok {
                WKInterfaceDevice.current().play(.success)
                dismiss()
            } else {
                failed = true
                WKInterfaceDevice.current().play(.failure)
            }
        }
    }
}
