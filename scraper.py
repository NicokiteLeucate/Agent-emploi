#!/usr/bin/env python3
# ============================================================
#  AGENT RECHERCHE EMPLOI - Nicolas Reichstadt
#  Utilise l'API officielle France Travail (ex Pole Emploi)
# ============================================================

# --- TA CONFIGURATION --------------------------------------
MOTS_CLES = [
    "methodes",
    "industrialisation",
    "chef de projet",
    "lean",
    "performance industrielle",
    "amelioration continue",
    "responsable methodes",
]

DEPARTEMENT = "76"          # Seine-Maritime
MAX_RESULTATS = 50          # par requete API (max 150)
EMAIL_DESTINATAIRE = "nicolas.reichstadt@gmail.com"
EMAIL_EXPEDITEUR   = "nicolas.reichstadt@gmail.com"
# -----------------------------------------------------------

import os
import re
import json
import smtplib
import hashlib
import requests
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Secrets GitHub
FT_CLIENT_ID     = os.environ.get("CLIENT_ID", "")
FT_CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "")
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
GMAIL_PASSWORD   = os.environ.get("GMAIL_PASSWORD", "")

FICHIER_HISTORIQUE = "historique_annonces.json"

# ============================================================
#  AUTHENTIFICATION FRANCE TRAVAIL
# ============================================================

def obtenir_token():
    """
    Obtient un token d'acces OAuth2 aupres de France Travail.
    Le token est valable 1500 secondes (~25 min), largement suffisant.
    """
    print("Authentification France Travail...")
    url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
    params = {"realm": "/partenaire"}
    data = {
        "grant_type":    "client_credentials",
        "client_id":     FT_CLIENT_ID,
        "client_secret": FT_CLIENT_SECRET,
        "scope":         "api_offresdemploiv2 o2dsoffre",
    }
    try:
        r = requests.post(url, params=params, data=data, timeout=15)
        print(f"  HTTP {r.status_code}")
        if r.status_code == 200:
            token = r.json().get("access_token", "")
            print("  Token obtenu avec succes")
            return token
        else:
            print(f"  ERREUR auth : {r.text[:300]}")
            return None
    except Exception as e:
        print(f"  EXCEPTION auth : {e}")
        return None

# ============================================================
#  RECHERCHE DES OFFRES
# ============================================================

def rechercher_offres(token, mot_cle):
    """
    Appelle l'API France Travail pour un mot-cle donne.
    Filtre sur le departement 76 et les offres des 24 dernieres heures.
    """
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept":        "application/json",
    }

    # Date d'hier pour ne recuperer que les nouvelles offres
    hier = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    aujourd_hui = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "motsCles":          mot_cle,
        "departement":       DEPARTEMENT,
        "minCreationDate":   hier,
        "maxCreationDate":   aujourd_hui,
        "range":             f"0-{MAX_RESULTATS - 1}",
        "sort":              "1",
    }

    try:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        print(f"  [{mot_cle}] HTTP {r.status_code}", end="")

        if r.status_code == 200:
            data = r.json()
            offres = data.get("resultats", [])
            print(f" — {len(offres)} offre(s)")
            return offres
        elif r.status_code == 204:
            print(" — aucune offre (204 No Content)")
            return []
        else:
            print(f" — ERREUR : {r.text[:200]}")
            return []
    except Exception as e:
        print(f" — EXCEPTION : {e}")
        return []

def normaliser_offre(offre):
    """Convertit une offre API en dictionnaire uniforme."""
    lieu = offre.get("lieuTravail", {})
    entreprise = offre.get("entreprise", {})
    return {
        "id":         offre.get("id", ""),
        "title":      offre.get("intitule", "Sans titre"),
        "entreprise": entreprise.get("nom", "Entreprise non precisee"),
        "lieu":       lieu.get("libelle", ""),
        "contrat":    offre.get("typeContratLibelle", ""),
        "salaire":    offre.get("salaire", {}).get("libelle", "Non precise"),
        "summary":    offre.get("description", "")[:400],
        "link":       offre.get("origineOffre", {}).get("urlOrigine",
                      f"https://candidat.francetravail.fr/offres/recherche/detail/{offre.get('id','')}"),
        "date":       offre.get("dateCreation", ""),
        "site":       "France Travail",
    }

# ============================================================
#  HISTORIQUE ANTI-DOUBLONS
# ============================================================

def charger_historique():
    if os.path.exists(FICHIER_HISTORIQUE):
        with open(FICHIER_HISTORIQUE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def sauvegarder_historique(historique):
    limite = datetime.now() - timedelta(days=30)
    filtre = []
    for h in historique:
        try:
            if datetime.fromisoformat(h.get("date", "2000-01-01")) > limite:
                filtre.append(h)
        except Exception:
            pass
    with open(FICHIER_HISTORIQUE, "w", encoding="utf-8") as f:
        json.dump(filtre, f, ensure_ascii=False, indent=2)

def id_offre(offre):
    """Identifiant unique base sur l'ID France Travail (plus fiable qu'un hash)."""
    return offre.get("id") or hashlib.md5(
        f"{offre.get('title','')}{offre.get('link','')}".encode()
    ).hexdigest()

# ============================================================
#  SYNTHESE GEMINI
# ============================================================

def synthetiser_avec_gemini(annonces):
    if not annonces:
        return "Aucune nouvelle annonce aujourd'hui."

    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

    liste_texte = ""
    for i, a in enumerate(annonces, 1):
        liste_texte += (
            f"\n{i}. {a['title']}\n"
            f"   Entreprise : {a['entreprise']}\n"
            f"   Lieu : {a['lieu']} | Contrat : {a['contrat']} | Salaire : {a['salaire']}\n"
            f"   Description : {a['summary']}\n"
            f"   Lien : {a['link']}\n"
        )

    prompt = (
        f"Tu es un assistant de recherche d'emploi. Voici {len(annonces)} nouvelles offres "
        f"trouvees aujourd'hui pour Nicolas, qui cherche des postes en methodes industrielles, "
        f"lean, amelioration continue ou chef de projet en Seine-Maritime.\n\n"
        f"{liste_texte}\n\n"
        f"Redige un email de synthese en francais avec :\n"
        f"1. Un resume global en 2-3 phrases sur la qualite des offres du jour\n"
        f"2. Pour chaque offre : titre, entreprise, lieu, contrat, resume en 1-2 phrases, lien\n"
        f"3. Un conseil du jour pour les candidatures dans ce secteur\n\n"
        f"Format : texte clair et lisible dans un email, sans markdown."
    )

    if not GROQ_API_KEY:
        # Fallback sans IA
        texte = f"{len(annonces)} nouvelles offres aujourd'hui :\n\n"
        for a in annonces:
            texte += (
                f"- {a['title']}\n"
                f"  Entreprise : {a['entreprise']}\n"
                f"  Lieu : {a['lieu']} | Contrat : {a['contrat']}\n"
                f"  Salaire : {a['salaire']}\n"
                f"  Lien : {a['link']}\n\n"
            )
        return texte

    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model":       "llama-3.3-70b-versatile",
            "messages":    [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens":  2000,
        }
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        data = r.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        else:
            print(f"Groq reponse inattendue : {data}")
            raise ValueError("Pas de choices dans la reponse")
    except Exception as e:
        print(f"Erreur Groq : {e}")
        texte = f"Synthese indisponible. {len(annonces)} offres du jour :\n\n"
        for a in annonces:
            texte += f"- {a['title']} — {a['entreprise']} ({a['lieu']})\n  {a['link']}\n\n"
        return texte
# ============================================================
#  ENVOI EMAIL
# ============================================================

def envoyer_email(sujet, corps):
    if not GMAIL_PASSWORD:
        print("GMAIL_PASSWORD manquant — contenu qui aurait ete envoye :")
        print("=" * 50)
        print(corps[:1000])
        print("=" * 50)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = sujet
    msg["From"]    = EMAIL_EXPEDITEUR
    msg["To"]      = EMAIL_DESTINATAIRE
    msg.attach(MIMEText(corps, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(EMAIL_EXPEDITEUR, GMAIL_PASSWORD)
            srv.sendmail(EMAIL_EXPEDITEUR, EMAIL_DESTINATAIRE, msg.as_string())
        print(f"Email envoye a {EMAIL_DESTINATAIRE}")
    except Exception as e:
        print(f"Erreur envoi email : {e}")

# ============================================================
#  MAIN
# ============================================================

def main():
    print(f"\n{'='*55}")
    print(f"  Agent emploi — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"  Departement : {DEPARTEMENT} (Seine-Maritime)")
    print(f"  Mots-cles : {len(MOTS_CLES)} termes")
    print(f"{'='*55}\n")

    # Verification des secrets
    if not FT_CLIENT_ID or not FT_CLIENT_SECRET:
        print("ERREUR : secrets client_id / client_secret manquants dans GitHub.")
        print("Va dans Settings -> Secrets -> Actions et verifie les noms.")
        return

    # 1. Authentification
    token = obtenir_token()
    if not token:
        print("Impossible d'obtenir le token France Travail. Arret.")
        return

    # 2. Charger l'historique
    historique = charger_historique()
    ids_vus = {h["id"] for h in historique}
    print(f"\nHistorique : {len(ids_vus)} offres deja connues\n")

    # 3. Recherche par mot-cle (logique OU)
    print("Recherche des offres...")
    toutes_offres = []
    ids_session = set()

    for mot in MOTS_CLES:
        offres_brutes = rechercher_offres(token, mot)
        for o in offres_brutes:
            offre = normaliser_offre(o)
            oid = id_offre(offre)
            if oid not in ids_vus and oid not in ids_session:
                offre["id"] = oid
                toutes_offres.append(offre)
                ids_session.add(oid)
                ids_vus.add(oid)
                historique.append({
                    "id":    oid,
                    "date":  datetime.now().isoformat(),
                    "titre": offre["title"],
                })

    print(f"\nTotal : {len(toutes_offres)} nouvelle(s) offre(s) unique(s)\n")

    # 4. Sauvegarder l'historique
    sauvegarder_historique(historique)

    # 5. Email
    date_str = datetime.now().strftime("%A %d %B %Y").capitalize()

    if toutes_offres:
        print("Synthese Gemini en cours...")
        synthese = synthetiser_avec_gemini(toutes_offres)
        sujet = f"[Agent emploi] {len(toutes_offres)} nouvelle(s) offre(s) — {date_str}"
    else:
        synthese = (
            f"Bonjour Nicolas,\n\n"
            f"Aucune nouvelle offre trouvee aujourd'hui en Seine-Maritime "
            f"pour tes criteres (methodes, lean, chef de projet...).\n\n"
            f"A demain !"
        )
        sujet = f"[Agent emploi] Aucune offre — {date_str}"

    envoyer_email(sujet, synthese)
    print("\nAgent termine avec succes.")

if __name__ == "__main__":
    main()
