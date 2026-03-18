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
#  CALCUL DISTANCE A VOL D'OISEAU DEPUIS CLERES
# ============================================================

import math

# Coordonnees GPS de Cleres (76690)
CLERES_LAT = 49.5986
CLERES_LON = 1.1194

# Coordonnees GPS des principales villes de Seine-Maritime
# et communes voisines
VILLES_GPS = {
    "rouen":           (49.4432, 1.0993),
    "le havre":        (49.4944, 0.1079),
    "dieppe":          (49.9225, 1.0750),
    "fecamp":          (49.7557, 0.3753),
    "yvetot":          (49.6196, 0.7561),
    "barentin":        (49.5461, 0.9572),
    "elbeuf":          (49.2833, 1.0167),
    "lillebonne":      (49.5167, 0.5333),
    "bolbec":          (49.5736, 0.4681),
    "montivilliers":   (49.5447, 0.1900),
    "gonfreville":     (49.5000, 0.2333),
    "harfleur":        (49.5097, 0.2003),
    "caudebec":        (49.5333, 0.7333),
    "duclair":         (49.4833, 0.8833),
    "maromme":         (49.4833, 1.0500),
    "deville":         (49.4667, 1.0500),
    "mont-saint-aignan":(49.4667, 1.0833),
    "bois-guillaume":  (49.4667, 1.1167),
    "bihorel":         (49.4500, 1.1167),
    "isneauville":     (49.5000, 1.1500),
    "cleres":          (49.5986, 1.1194),
    "buchy":           (49.5833, 1.3500),
    "forges-les-eaux": (49.6167, 1.5500),
    "neufchatel":      (49.7333, 1.4333),
    "eu":              (50.0500, 1.4167),
    "saint-valery":    (49.8667, 0.7167),
    "etretat":         (49.7083, 0.2028),
    "goderville":      (49.6333, 0.3667),
    "lillebonne":      (49.5167, 0.5333),
    "vernon":          (49.0931, 1.4833),
    "gisors":          (49.2833, 1.7833),
}

def calculer_distance_km(lat1, lon1, lat2, lon2):
    """Distance en km entre deux points GPS (formule haversine)."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))

def estimer_trajet(lieu):
    """
    Estime le temps de trajet en voiture depuis Cleres.
    - Cherche la ville dans le texte du lieu
    - Calcule la distance a vol d'oiseau
    - Applique vitesse moyenne 70 km/h + 10 min forfait (sorties/entrees ville)
    - Retourne (minutes, ville_trouvee)
    """
    if not lieu:
        return None, None

    lieu_lower = lieu.lower()

    # Si juste "Seine-Maritime" ou "76" sans ville = Cleres
    if lieu_lower in ["seine-maritime", "76", "seine maritime", ""]:
        return 0, "Cleres"

    # Cherche une ville connue dans le lieu
    for ville, (lat, lon) in VILLES_GPS.items():
        if ville in lieu_lower:
            dist_km = calculer_distance_km(CLERES_LAT, CLERES_LON, lat, lon)
            # Vitesse moyenne 70 km/h + 10 min forfait depart/arrivee
            minutes = int((dist_km / 70) * 60) + 10
            return minutes, ville.capitalize()

    # Ville non trouvee dans le dictionnaire
    re

# ============================================================
#  SYNTHESE GEMINI
# ============================================================
def synthetiser_avec_gemini(annonces):
    if not annonces:
        return "Aucune nouvelle annonce aujourd'hui."

    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

    # Calcul des distances AVANT d'appeler Groq
    for a in annonces:
        minutes, ville = estimer_trajet(a.get("lieu", ""))
        a["trajet_minutes"] = minutes
        a["trajet_ville"]   = ville

    # Trier : proches d'abord, lointaines ensuite
    proches   = [a for a in annonces if a["trajet_minutes"] is not None and a["trajet_minutes"] <= 45]
    lointaines = [a for a in annonces if a["trajet_minutes"] is not None and a["trajet_minutes"] > 45]
    inconnues  = [a for a in annonces if a["trajet_minutes"] is None]

    def formater_offre(a, mention_loin=False):
        if a["trajet_minutes"] == 0:
            trajet_str = "Cleres ou alentours (< 5 min)"
        elif a["trajet_minutes"] is not None:
            loin = " (LOIN)" if mention_loin else ""
            trajet_str = f"~{a['trajet_minutes']} min depuis Cleres{loin}"
        else:
            trajet_str = "Distance non calculee (ville non reconnue)"
        return (
            f"  Poste    : {a['title']}\n"
            f"  Societe  : {a['entreprise']}\n"
            f"  Lieu     : {a['lieu']} | Contrat : {a['contrat']}\n"
            f"  Salaire  : {a['salaire']}\n"
            f"  Trajet   : {trajet_str}\n"
            f"  Lien     : {a['link']}\n"
        )

    # Construction de l'email sans IA si pas de cle Groq
    if not GROQ_API_KEY:
        email = f"{len(annonces)} nouvelles offres aujourd'hui\n"
        email += "=" * 50 + "\n\n"
        if proches:
            email += f"OFFRES PROCHES ({len(proches)}) — moins de 45 min\n"
            email += "-" * 40 + "\n"
            for a in proches:
                email += formater_offre(a) + "\n"
        if lointaines:
            email += f"\nOFFRES LOINTAINES ({len(lointaines)}) — plus de 45 min\n"
            email += "-" * 40 + "\n"
            for a in lointaines:
                email += formater_offre(a, mention_loin=True) + "\n"
        if inconnues:
            email += f"\nOFFRES LIEU INCONNU ({len(inconnues)})\n"
            email += "-" * 40 + "\n"
            for a in inconnues:
                email += formater_offre(a) + "\n"
        return email

    # Construction du prompt pour Groq avec distances deja calculees
    def section(titre, liste, loin=False):
        if not liste:
            return ""
        texte = f"\n{titre}\n" + "-" * 40 + "\n"
        for a in liste:
            texte += formater_offre(a, mention_loin=loin)
            texte += f"  Description : {a['summary'][:250]}\n\n"
        return texte

    contenu = (
        section(f"OFFRES PROCHES ({len(proches)}) — moins de 45 min de Cleres", proches) +
        section(f"OFFRES LOINTAINES ({len(lointaines)}) — plus de 45 min de Cleres", lointaines, loin=True) +
        section(f"OFFRES LIEU INCONNU ({len(inconnues)})", inconnues)
    )

    prompt = (
        f"Tu es un assistant de recherche d'emploi pour Nicolas, "
        f"qui habite a Cleres (Seine-Maritime) et cherche des postes "
        f"en methodes industrielles, lean, amelioration continue ou chef de projet.\n\n"
        f"Voici {len(annonces)} nouvelles offres du jour avec leurs distances "
        f"deja calculees depuis Cleres :\n"
        f"{contenu}\n\n"
        f"Redige un email de synthese structure ainsi :\n"
        f"1. Introduction : resume global en 2-3 phrases\n"
        f"2. Offres proches : reprend chaque offre avec trajet, resume 1-2 phrases, lien\n"
        f"3. Offres lointaines : idem, en precisant que c'est loin\n"
        f"4. Offres lieu inconnu : liste simple\n"
        f"5. Conseil du jour : un conseil pratique pour ce secteur\n\n"
        f"NE recalcule PAS les distances, utilise exactement celles fournies.\n"
        f"Format : texte lisible dans un email, sans markdown, sans asterisques."
    )

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
            "max_tokens":  3000,
        }
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        data = r.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        else:
            print(f"Groq reponse inattendue : {data}")
            raise ValueError("Pas de choices")
    except Exception as e:
        print(f"Erreur Groq : {e}")
        return contenu
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
