// Adresse du Pi et jeton de l'API télécommande (REMOTE_API_TOKEN du .env).
// ⚠️ Le jeton se colle ICI, sur le Mac uniquement : jamais dans le dépôt ni par mail.
enum Secrets {
    static let baseURL = "http://192.168.1.52:8766"
    static let token = "COLLER_LE_JETON_ICI"
}
