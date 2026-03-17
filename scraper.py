#!/usr/bin/env python3
# ============================================================
#  AGENT RECHERCHE EMPLOI - Nicolas Reichstadt
#  Configure tes préférences dans la section ci-dessous
#  Tout le reste est automatique !
# ============================================================

# --- TA CONFIGURATION (seule partie à modifier) -------------
MOTS_CLES = [
    "méthodes",
    "industrialisation",
    "chef de projet",
    "lean",
    "performance industrielle",
    "amélioration continue",
    "responsable méthodes",
]

ZONE_GEO = "Seine-Maritime"   # utilisé pour filtrer les annonces

EMAIL_DESTINATAIRE = "nicolas.reichstadt@gmail.com"
EMAIL_EXPEDITEUR   = "nicolas.reichstadt@gmail.com"  # ton Gmail (expéditeur = toi)

# Nombre max d'annonces par site dans l'email
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

# Clés récupérées depuis les secrets GitHub (jamais écrites dans le code)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GMAIL_PASSWORD  = os.environ.get("GMAIL_PASSWORD", "")

# Fichier qui mémorise les annonces déjà envoyées (évite les doublons)
FICHIER_HISTORIQUE = "historique_annonces.json"

# ============================================================
#  FLUX RSS DES SITES D'EMPLOI
# ============================================================

def construire_flux_rss():
    """
    Construit les URLs RSS pour chaque site.
    On crée UN flux par mot-clé (logique OU) plutôt qu'un seul flux
    avec tous les mots ensemble (qui ferait un ET implicite).
    """
    flux = {}
    zone_encodée = ZONE_GEO.replace(" ", "+").replace("-", "+")

    for mot in MOTS_CLES:
        mot_encodé = mot.replace(" ", "%20")
        mot_url    = mot.replace(" ", "+")

        # APEC — un flux par mot-clé
        flux[f"APEC | {mot}"] = (
            f"https://www.apec.fr/candidat/recherche-emploi.html/emploi?"
            f"motsCles={mot_encodé}&lieu=76&typesContrat=1&page=1&format=rss"
        )

        # Welcome to the Jungle — un flux par mot-clé
        flux[f"WTTJ | {mot}"] = (
            f"https://www.welcometothejungle.com/fr/jobs.rss?"
            f"query={mot_encodé}&aroundQuery={zone_encodée}&page=1"
        )

        # Indeed — un flux par mot-clé
        flux[f"Indeed | {mot}"] = (
            f"https://fr.indeed.com/rss?q={mot_url}"
            f"&l={zone_encodée}&sort=date&fromage=1"
        )

    return flux

# ============================================================
#  CHARGEMENT / SAUVEGARDE DE L'HISTORIQUE
# ============================================================

def charger_historique():
    """Charge la liste des annonces déjà vues."""
    if os.path.exists(FICHIER_HISTORIQUE):
        with open(FICHIER_HISTORIQUE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def sauvegarder_historique(historique):
    """Sauvegarde la liste des annonces vues (garde 30 jours max)."""
    limite = datetime.now() - timedelta(days=30)
    historique_filtre = [
        h for h in historique
        if datetime.fromisoformat(h.get("date", "2000-01-01")) > limite
    ]
    with open(FICHIER_HISTORIQUE, "w", encoding="utf-8") as f:
        json.dump(historique_filtre, f, ensure_ascii=False, indent=2)

def id_annonce(annonce):
    """Génère un identifiant unique pour une annonce."""
    chaine = f"{annonce.get('title','')}{annonce.get('link','')}"
    return hashlib.md5(chaine.encode()).hexdigest()

# ============================================================
#  SCRAPING DES FLUX RSS
# ============================================================

def est_pertinente(annonce):
    """Vérifie si une annonce correspond aux mots-clés et à la zone."""
    texte = (
        annonce.get("title", "") + " " +
        annonce.get("summary", "") + " " +
        annonce.get("location", "")
    ).lower()

    # Filtre géographique (Seine-Maritime = 76, Rouen, Le Havre, Dieppe...)
    zones_acceptées = [
        "seine-maritime", "seine maritime", "76",
        "rouen", "le havre", "dieppe", "fécamp", "elbeuf",
        "normandie", "remote", "télétravail", "distanciel"
    ]
    zone_ok = any(z in texte for z in zones_acceptées)
    if not zone_ok:
        return False

    # Filtre mots-clés (au moins 1 mot-clé doit apparaître)
    mots_ok = any(mot.lower() in texte for mot in MOTS_CLES)
    return mots_ok

def scraper_flux(nom_site, url_rss):
    """Récupère et filtre les annonces d'un flux RSS."""
    annonces = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (agent-emploi-rss-reader/1.0)"}
        response = requests.get(url_rss, headers=headers, timeout=15)
        feed = feedparser.parse(response.content)

        for entry in feed.entries:
            annonce = {
                "title":    entry.get("title", "Sans titre"),
                "link":     entry.get("link", ""),
                "summary":  re.sub(r"<[^>]+>", " ", entry.get("summary", "")),
                "location": entry.get("location", ""),
                "date":     entry.get("published", ""),
                "site":     nom_site,
            }
            if est_pertinente(annonce):
                annonces.append(annonce)

    except Exception as e:
        print(f"[{nom_site}] Erreur : {e}")

    return annonces[:MAX_ANNONCES_PAR_SITE]

# ============================================================
#  SYNTHÈSE IA AVEC GEMINI
# ============================================================

def synthétiser_avec_gemini(annonces):
    """Envoie les annonces à Gemini et récupère une synthèse structurée."""
    if not annonces:
        return "Aucune nouvelle annonce aujourd'hui."

    if not GEMINI_API_KEY:
        return "⚠️ Clé Gemini manquante — synthèse IA désactivée."

    liste_texte = ""
    for i, a in enumerate(annonces, 1):
        liste_texte += (
            f"\n{i}. [{a['site']}] {a['title']}\n"
            f"   Résumé : {a['summary'][:300]}\n"
            f"   Lien : {a['link']}\n"
        )

    prompt = f"""Tu es un assistant de recherche d'emploi. Voici {len(annonces)} nouvelles offres d'emploi trouvées aujourd'hui pour Nicolas, qui cherche des postes en méthodes, industrialisation, lean, amélioration continue ou chef de projet en Seine-Maritime.

{liste_texte}

Rédige un email de synthèse en français avec :
1. Un court résumé global (2-3 phrases) sur la qualité des offres du jour
2. Pour chaque annonce : le titre, l'entreprise si mentionnée, un résumé en 1-2 phrases, et le lien
3. Un conseil du jour sur la candidature ou la recherche d'emploi dans ce secteur

Format : texte simple, pas de markdown, lisible directement dans un email."""

    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-1.5-flash:generateContent"
            f"?key={GEMINI_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000}
        }
        response = requests.post(url, json=payload, timeout=30)
        data = response.json()
        return (
            data["candidates"][0]["content"]["parts"][0]["text"]
        )
    except Exception as e:
        print(f"Erreur Gemini : {e}")
        # Fallback : liste brute sans IA
        fallback = "Synthèse IA indisponible — voici les annonces brutes :\n\n"
        for a in annonces:
            fallback += f"• {a['title']} ({a['site']})\n  {a['link']}\n\n"
        return fallback

# ============================================================
#  ENVOI DE L'EMAIL
# ============================================================

def envoyer_email(sujet, corps):
    """Envoie l'email de résumé via Gmail SMTP."""
    if not GMAIL_PASSWORD:
        print("⚠️ GMAIL_PASSWORD manquant — email non envoyé.")
        print("--- CONTENU QUI AURAIT ÉTÉ ENVOYÉ ---")
        print(corps)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = sujet
    msg["From"]    = EMAIL_EXPEDITEUR
    msg["To"]      = EMAIL_DESTINATAIRE

    # Version texte plain
    msg.attach(MIMEText(corps, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as serveur:
            serveur.login(EMAIL_EXPEDITEUR, GMAIL_PASSWORD)
            serveur.sendmail(EMAIL_EXPEDITEUR, EMAIL_DESTINATAIRE, msg.as_string())
        print(f"✅ Email envoyé à {EMAIL_DESTINATAIRE}")
    except Exception as e:
        print(f"❌ Erreur envoi email : {e}")

# ============================================================
#  PROGRAMME PRINCIPAL
# ============================================================

def main():
    print(f"\n{'='*50}")
    print(f"  Agent emploi - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*50}\n")

    # 1. Charger l'historique des annonces déjà vues
    historique = charger_historique()
    ids_vus = {h["id"] for h in historique}
    print(f"📋 Historique : {len(ids_vus)} annonces déjà connues\n")

    # 2. Scraper tous les sites (un flux par mot-clé = logique OU)
    flux = construire_flux_rss()
    nouvelles_annonces = []
    ids_session = set()   # évite les doublons dans la même session
                          # (même annonce trouvée par 2 mots-clés différents)
    sites_compteurs = {}

    for nom_flux, url_rss in flux.items():
        nom_site = nom_flux.split(" | ")[0]
        print(f"🔍 {nom_flux}...")
        annonces = scraper_flux(nom_site, url_rss)

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

        sites_compteurs[nom_site] = sites_compteurs.get(nom_site, 0) + nb_nouvelles
        print(f"   -> {nb_nouvelles} nouvelle(s) (doublons ignores)")

    print(f"\nResume par site :")
    for site, nb in sites_compteurs.items():
        print(f"   {site} : {nb} nouvelle(s)")
    print(f"\n{len(nouvelles_annonces)} nouvelle(s) annonce(s) uniques au total\n")

    # 3. Sauvegarder l'historique mis à jour
    sauvegarder_historique(historique)

    # 4. Construire et envoyer l'email
    date_str = datetime.now().strftime("%A %d %B %Y").capitalize()

    if nouvelles_annonces:
        print("🤖 Synthèse avec Gemini en cours...")
        synthèse = synthétiser_avec_gemini(nouvelles_annonces)
        sujet = f"🎯 {len(nouvelles_annonces)} nouvelle(s) offre(s) d'emploi — {date_str}"
    else:
        synthèse = (
            f"Bonjour Nicolas,\n\n"
            f"Aucune nouvelle offre trouvée aujourd'hui correspondant à tes critères "
            f"(méthodes / lean / chef de projet en Seine-Maritime).\n\n"
            f"L'agent a vérifié : {', '.join(flux.keys())}\n\n"
            f"À demain !"
        )
        sujet = f"Agent emploi — Aucune nouvelle offre — {date_str}"

    envoyer_email(sujet, synthèse)
    print("\n✅ Agent terminé avec succès.")

if __name__ == "__main__":
    main()
