// Adresse du Pi, jeton de l'API télécommande (REMOTE_API_TOKEN du .env), clé IDFM
// et domicile (trajet retour). Valeurs factices ici : la CI TestFlight réécrit ce
// fichier depuis les secrets GitHub. ⚠️ Jamais de vraie valeur dans le dépôt (public).
enum Secrets {
    static let baseURL = "http://192.168.1.52:8766"
    static let token = "COLLER_LE_JETON_ICI"
    static let idfmKey = ""                 // vide = pas de trajet retour
    static let homeLat = 0.0
    static let homeLon = 0.0
}
