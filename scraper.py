#!/usr/bin/env python3
# ============================================================
#  AGENT RECHERCHE EMPLOI - Nicolas Reichstadt
#  Source : API officielle France Travail
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

DEPARTEMENT        = "76"
MAX_RESULTATS_FT   = 50
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

CLIENT_ID      = os.environ.get("CLIENT_ID", "")
CLIENT_SECRET  = os.environ.get("CLIENT_SECRET", "")
GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")

FICHIER_HISTORIQUE = "historique_annonces.json"

# ============================================================
#  AUTHENTIFICATION FRANCE TRAVAIL
# ============================================================

def obtenir_token():
    print("Authentification France Travail...")
    url    = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
    params = {"realm": "/partenaire"}
    data   = {
        "grant_type":    "client_credentials",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope":         "api_offresdemploiv2 o2dsoffre",
    }
    try:
        r = requests.post(url, params=params, data=data, timeout=15)
        print(f"  HTTP {r.status_code}")
        if r.status_code == 200:
            print("  Token obtenu avec succes")
            return r.json().get("access_token", "")
        else:
            print(f"  ERREUR auth : {r.text[:300]}")
            return None
    except Exception as e:
        print(f"  EXCEPTION auth : {e}")
        return None

# ============================================================
#  RECHERCHE FRANCE TRAVAIL
# ============================================================

def rechercher_offres_ft(token, mot_cle):
    url     = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    hier        = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    aujourd_hui = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    params  = {
        "motsCles":        mot_cle,
        "departement":     DEPARTEMENT,
        "minCreationDate": hier,
        "maxCreationDate": aujourd_hui,
        "range":           f"0-{MAX_RESULTATS_FT - 1}",
        "sort":            "1",
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        print(f"  [{mot_cle}] HTTP {r.status_code}", end="")
        if r.status_code == 200:
            offres = r.json().get("resultats", [])
            print(f" — {len(offres)} offre(s)")
            return offres
        elif r.status_code == 204:
            print(" — aucune offre")
            return []
        else:
            print(f" — ERREUR : {r.text[:200]}")
            return []
    except Exception as e:
        print(f" — EXCEPTION : {e}")
        return []

def normaliser_offre_ft(offre):
    lieu       = offre.get("lieuTravail", {})
    entreprise = offre.get("entreprise", {})
    return {
        "id":         offre.get("id", ""),
        "title":      offre.get("intitule", "Sans titre"),
        "entreprise": entreprise.get("nom", "Non precisee"),
        "lieu":       lieu.get("libelle", "Seine-Maritime"),
        "contrat":    offre.get("typeContratLibelle", "Non precise"),
        "salaire":    offre.get("salaire", {}).get("libelle", "Non precise"),
        "summary":    offre.get("description", "")[:400],
        "link":       offre.get("origineOffre", {}).get(
                          "urlOrigine",
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
    if offre.get("id"):
        return str(offre["id"])
    return hashlib.md5(
        f"{offre.get('title','')}{offre.get('link','')}".encode()
    ).hexdigest()

# ============================================================
#  SYNTHESE GROQ
# ============================================================

def synthetiser(annonces):
    if not annonces:
        return "Aucune nouvelle annonce aujourd'hui."

    liste_texte = ""
    for i, a in enumerate(annonces, 1):
        liste_texte += (
            f"\n{i}. {a['title']}\n"
            f"   Entreprise : {a['entreprise']}\n"
            f"   Lieu : {a['lieu']} | Contrat : {a['contrat']} | Salaire : {a['salaire']}\n"
            f"   Description : {a['summary']}\n"
            f"   Lien : {a['link']}\n"
        )

    if not GROQ_API_KEY:
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

    prompt = (
        f"Tu es un assistant de recherche d'emploi pour Nicolas, "
        f"qui cherche des postes en methodes industrielles, lean, "
        f"amelioration continue ou chef de projet en Seine-Maritime.\n\n"
        f"Voici {len(annonces)} nouvelles offres du jour :\n"
        f"{liste_texte}\n\n"
        f"Redige un email de synthese en francais structure ainsi :\n"
        f"1. Introduction : resume global en 2-3 phrases sur la qualite des offres\n"
        f"2. Pour chaque offre : titre, entreprise, lieu, contrat, salaire, "
        f"resume en 1-2 phrases, lien\n"
        f"3. Conseil du jour : un conseil pratique pour les candidatures "
        f"dans le secteur methodes/lean/industrie\n\n"
        f"Format : texte clair et lisible dans un email, sans markdown, sans asterisques."
    )

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       "llama-3.3-70b-versatile",
                "messages":    [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens":  3000,
            },
            timeout=30,
        )
        data = r.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        else:
            print(f"Groq reponse inattendue : {data}")
            raise ValueError("Pas de choices")
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
        print("GMAIL_PASSWORD manquant — contenu :")
        print("=" * 50)
        print(corps[:1000])
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

    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERREUR : secrets CLIENT_ID / CLIENT_SECRET manquants.")
        return

    historique      = charger_historique()
    ids_vus         = {h["id"] for h in historique}
    ids_session     = set()
    toutes_offres   = []

    def ajouter_offre(offre):
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
            return True
        return False

    # --- France Travail ---
    print("--- France Travail (API officielle) ---")
    token = obtenir_token()
    if token:
        nb_ft = 0
        for mot in MOTS_CLES:
            offres_brutes = rechercher_offres_ft(token, mot)
            nb_ft += sum(1 for o in offres_brutes if ajouter_offre(normaliser_offre_ft(o)))
        print(f"\n  France Travail : {nb_ft} nouvelle(s) offre(s) uniques")
    else:
        print("Token indisponible — arret.")
        return

    # Bilan
    print(f"\n--- Bilan ---")
    print(f"  TOTAL : {len(toutes_offres)} offre(s) unique(s)\n")

    sauvegarder_historique(historique)

    date_str = datetime.now().strftime("%A %d %B %Y").capitalize()
    if toutes_offres:
        print("Synthese en cours...")
        synthese = synthetiser(toutes_offres)
        sujet    = f"[Agent emploi] {len(toutes_offres)} nouvelle(s) offre(s) — {date_str}"
    else:
        synthese = (
            f"Bonjour Nicolas,\n\n"
            f"Aucune nouvelle offre trouvee aujourd'hui en Seine-Maritime.\n"
            f"Mots-cles surveilles : {', '.join(MOTS_CLES)}\n\n"
            f"A demain !"
        )
        sujet = f"[Agent emploi] Aucune offre — {date_str}"

    envoyer_email(sujet, synthese)
    print("\nAgent termine avec succes.")

if __name__ == "__main__":
    main()
