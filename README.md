# 🚀 Amazon Account Generator - Railway

Application web mobile-friendly pour générer des comptes Amazon depuis ton téléphone.

## 📱 Fonctionnalités

- Interface PWA (ajouter à l'écran d'accueil)
- Voir le nombre d'emails restants
- Résoudre les captchas directement sur mobile
- Génération automatique sur le serveur
- Temps réel via WebSocket

## 🔧 Variables d'environnement Railway

Configure ces variables dans ton projet Railway :

| Variable | Description | Exemple |
|----------|-------------|---------|
| `AMAZON_PASSWORD` | Mot de passe pour les comptes | `MonMotDePasse123!` |
| `IMAP_USER` | Email iCloud | `monmail@icloud.com` |
| `IMAP_PASSWORD` | Mot de passe app iCloud | `xxxx-xxxx-xxxx-xxxx` |
| `HEROSMS_API_KEY` | Clé API Hero SMS | `abc123...` |
| `SECRET_KEY` | Clé secrète Flask | `random-secret-key` |

### Variables optionnelles

| Variable | Description | Défaut |
|----------|-------------|--------|
| `ARKOSE_PUBLIC_KEY` | Clé publique Arkose | `56938EF5-...` |
| `IMAP_SERVER` | Serveur IMAP | `imap.mail.me.com` |
| `IMAP_PORT` | Port IMAP | `993` |
| `HEROSMS_BASE_URL` | URL API Hero SMS | `https://hero-sms.com/...` |

## 🚀 Déploiement sur Railway

1. **Fork/Push ce repo sur GitHub**

2. **Créer un projet Railway**
   - Aller sur [railway.app](https://railway.app)
   - New Project → Deploy from GitHub repo
   - Sélectionner ce repo

3. **Configurer les variables**
   - Aller dans Settings → Variables
   - Ajouter toutes les variables listées ci-dessus

4. **Déployer**
   - Railway détecte automatiquement le Dockerfile
   - Le déploiement démarre

5. **Obtenir l'URL**
   - Settings → Domains → Generate Domain
   - Tu obtiens une URL comme `amazon-xxx.up.railway.app`

## 📱 Installation sur iPhone

1. Ouvrir l'URL dans Safari
2. Appuyer sur le bouton Partager (carré avec flèche)
3. "Sur l'écran d'accueil"
4. L'app apparaît comme une app native!

## 📧 Ajouter des emails

Pour l'instant, tu dois ajouter les emails manuellement via Railway :

1. Railway → ton projet → Shell
2. `echo "email1@icloud.com" >> emails.txt`
3. `echo "email2@icloud.com" >> emails.txt`

Ou utiliser l'API (à implémenter) pour uploader un fichier.

## 🔒 Sécurité

- Ne commit jamais tes credentials
- Utilise les variables d'environnement Railway
- Le fichier `.gitignore` exclut les fichiers sensibles

## 📝 Logs

Voir les logs en temps réel :
- Railway → ton projet → Deployments → View Logs
