#!/usr/bin/env python3
# ============================================================
#  AGENT RECHERCHE EMPLOI - Nicolas Reichstadt
#  Configure tes preferences dans la section ci-dessous
# ============================================================

# --- TA CONFIGURATION (seule partie a modifier) -------------
MOTS_CLES = [
    "methodes",
    "industrialisation",
    "chef de projet",
    "lean",
    "performance industrielle",
    "amelioration continue",
    "responsable methodes",
]

# Mots acceptes dans le texte de l'annonce pour la zone geo
ZONES_GEO = [
    "seine-maritime", "seine maritime", "76",
    "rouen", "le havre", "havre", "dieppe", "fecamp", "elbeuf",
    "barentin", "yvetot", "montivilliers", "bolbec",
    "normandie", "haute-normandie",
    "remote", "teletravail", "distanciel", "france entiere",
]

# Mettre a False pour recevoir TOUTES les annonces sans filtre geo
# (utile pour diagnostiquer si le probleme vient du filtre)
FILTRER_PAR_ZONE = False

EMAIL_DESTINATAIRE = "nicolas.reichstadt@gmail.com"
EMAIL_EXPEDITEUR   = "nicolas.reichstadt@gmail.com"

MAX_ANNONCES_PAR_SITE = 10
# ------------------------------------------------------------

import os
import re
import json
import smtplib
import hashlib
import feedparser
import requests
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GMAIL_PASSWORD  = os.environ.get("GMAIL_PASSWORD", "")
FICHIER_HISTORIQUE = "historique_annonces.json"

# ============================================================
#  FLUX RSS - UN PAR MOT-CLE (logique OU)
# ============================================================

def construire_flux_rss():
    flux = {}
    for mot in MOTS_CLES:
        mot_url = mot.replace(" ", "+")
        mot_pct = mot.replace(" ", "%20")

        # APEC - code departement 76 = Seine-Maritime
        flux[f"APEC|{mot}"] = (
            f"https://www.apec.fr/candidat/recherche-emploi.html/emploi"
            f"?motsCles={mot_pct}&lieu=76&page=1&format=rss"
        )

        # Indeed France - fromage=1 = annonces des 24 dernieres heures
        flux[f"Indeed|{mot}"] = (
            f"https://fr.indeed.com/rss?q={mot_url}&l=Seine-Maritime"
            f"&sort=date&fromage=1"
        )

        # Welcome to the Jungle
        flux[f"WTTJ|{mot}"] = (
            f"https://www.welcometothejungle.com/fr/jobs.rss"
            f"?query={mot_pct}&aroundQuery=Seine-Maritime&page=1"
        )

    return flux

# ============================================================
#  HISTORIQUE (anti-doublons entre les jours)
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

def id_annonce(annonce):
    chaine = f"{annonce.get('title','')}{annonce.get('link','')}"
    return hashlib.md5(chaine.encode()).hexdigest()

# ============================================================
#  FILTRE PERTINENCE
# ============================================================

def est_pertinente(annonce):
    texte = (
        annonce.get("title", "") + " " +
        annonce.get("summary", "") + " " +
        annonce.get("location", "")
    ).lower()

    if FILTRER_PAR_ZONE:
        if not any(z in texte for z in ZONES_GEO):
            return False

    return any(mot.lower() in texte for mot in MOTS_CLES)

# ============================================================
#  SCRAPING avec diagnostics detailles
# ============================================================

def scraper_flux(nom_flux, url_rss):
    nom_site = nom_flux.split("|")[0]
    annonces = []
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(url_rss, headers=headers, timeout=20)
        print(f"   HTTP {response.status_code} — {len(response.content)} octets")

        if response.status_code != 200:
            print(f"   ERREUR : {response.text[:200]}")
            return []

        feed = feedparser.parse(response.content)
        nb = len(feed.entries)
        print(f"   {nb} entree(s) dans le flux RSS")

        if nb == 0:
            print(f"   Contenu brut (200 premiers chars) : {response.text[:200]}")
            return []

        rejets_zone = 0
        rejets_mots = 0
        for entry in feed.entries:
            annonce = {
                "title":    entry.get("title", "Sans titre"),
                "link":     entry.get("link", ""),
                "summary":  re.sub(r"<[^>]+>", " ", entry.get("summary", "")),
                "location": entry.get("location", ""),
                "date":     entry.get("published", ""),
                "site":     nom_site,
            }
            texte = (annonce["title"] + " " + annonce["summary"] + " " + annonce["location"]).lower()
            zone_ok = any(z in texte for z in ZONES_GEO)
            mots_ok = any(m.lower() in texte for m in MOTS_CLES)

            if FILTRER_PAR_ZONE and not zone_ok:
                rejets_zone += 1
            elif not mots_ok:
                rejets_mots += 1
            else:
                annonces.append(annonce)

        if rejets_zone > 0:
            print(f"   {rejets_zone} rejet(s) : zone geo non reconnue")
        if rejets_mots > 0:
            print(f"   {rejets_mots} rejet(s) : mots-cles absents")
        if annonces:
            print(f"   {len(annonces)} annonce(s) retenue(s)")

    except Exception as e:
        print(f"   EXCEPTION : {e}")

    return annonces[:MAX_ANNONCES_PAR_SITE]

# ============================================================
#  SYNTHESE GEMINI
# ============================================================

def synthetiser_avec_gemini(annonces):
    if not annonces:
        return "Aucune nouvelle annonce aujourd'hui."
    if not GEMINI_API_KEY:
        return "Cle Gemini manquante — liste brute :\n\n" + "\n".join(
            f"- {a['title']} ({a['site']})\n  {a['link']}" for a in annonces
        )

    liste_texte = ""
    for i, a in enumerate(annonces, 1):
        liste_texte += (
            f"\n{i}. [{a['site']}] {a['title']}\n"
            f"   Resume : {a['summary'][:300]}\n"
            f"   Lien : {a['link']}\n"
        )

    prompt = (
        f"Tu es un assistant de recherche d'emploi. Voici {len(annonces)} nouvelles offres "
        f"trouvees aujourd'hui pour Nicolas, qui cherche des postes en methodes industrielles, "
        f"lean, amelioration continue ou chef de projet en Seine-Maritime.\n\n"
        f"{liste_texte}\n\n"
        f"Redige un email de synthese en francais avec :\n"
        f"1. Un court resume global (2-3 phrases)\n"
        f"2. Pour chaque annonce : titre, entreprise si connue, resume en 1-2 phrases, lien\n"
        f"3. Un conseil du jour pour les candidatures dans ce secteur\n\n"
        f"Format : texte simple, lisible dans un email."
    )

    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000}
        }
        r = requests.post(url, json=payload, timeout=30)
        data = r.json()
        if "candidates" in data:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            print(f"Gemini reponse inattendue : {data}")
            raise ValueError("Pas de candidates")
    except Exception as e:
        print(f"Erreur Gemini : {e}")
        return "Synthese indisponible.\n\n" + "\n".join(
            f"- {a['title']} ({a['site']})\n  {a['link']}" for a in annonces
        )

# ============================================================
#  ENVOI EMAIL
# ============================================================

def envoyer_email(sujet, corps):
    if not GMAIL_PASSWORD:
        print("GMAIL_PASSWORD manquant — email non envoye.")
        print("=== CONTENU QUI AURAIT ETE ENVOYE ===")
        print(corps)
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
    print(f"  Filtre zone : {'ACTIF' if FILTRER_PAR_ZONE else 'DESACTIVE (mode debug)'}")
    print(f"{'='*55}\n")

    historique = charger_historique()
    ids_vus = {h["id"] for h in historique}
    print(f"Historique : {len(ids_vus)} annonces deja connues\n")

    flux = construire_flux_rss()
    nouvelles_annonces = []
    ids_session = set()
    sites_compteurs = {}

    for nom_flux, url_rss in flux.items():
        print(f">>> {nom_flux}")
        annonces = scraper_flux(nom_flux, url_rss)

        nb_nouvelles = 0
        for annonce in annonces:
            aid = id_annonce(annonce)
            if aid not in ids_vus and aid not in ids_session:
                annonce["id"] = aid
                nouvelles_annonces.append(annonce)
                ids_session.add(aid)
                ids_vus.add(aid)
                historique.append({
                    "id":    aid,
                    "date":  datetime.now().isoformat(),
                    "titre": annonce["title"],
                })
                nb_nouvelles += 1

        nom_site = nom_flux.split("|")[0]
        sites_compteurs[nom_site] = sites_compteurs.get(nom_site, 0) + nb_nouvelles
        print()

    print("--- Bilan ---")
    for site, nb in sites_compteurs.items():
        print(f"  {site} : {nb} nouvelle(s)")
    print(f"  TOTAL : {len(nouvelles_annonces)} annonce(s) unique(s)\n")

    sauvegarder_historique(historique)

    date_str = datetime.now().strftime("%A %d %B %Y").capitalize()

    if nouvelles_annonces:
        print("Synthese Gemini en cours...")
        synthese = synthetiser_avec_gemini(nouvelles_annonces)
        sujet = f"[Agent emploi] {len(nouvelles_annonces)} nouvelle(s) offre(s) — {date_str}"
    else:
        synthese = (
            f"Bonjour Nicolas,\n\n"
            f"Aucune nouvelle offre trouvee aujourd'hui.\n"
            f"Sites verifies : APEC, Indeed, Welcome to the Jungle\n"
            f"Mots-cles : {', '.join(MOTS_CLES)}\n\n"
            f"A demain !"
        )
        sujet = f"[Agent emploi] Aucune offre — {date_str}"

    envoyer_email(sujet, synthese)
    print("Agent termine.")

if __name__ == "__main__":
    main()
