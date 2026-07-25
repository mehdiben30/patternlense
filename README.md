# PatternLens

Prototype local qui transforme une requête tactique en français en une règle
formelle, puis l’exécutera de manière déterministe sur le match ouvert
Köln–Bayern (`J03WMX`). Le projet est pour l’instant au stade du squelette
technique et du chargement des données.

## État actuel

L’environnement Python, Streamlit et les dépendances du MVP sont installés.
Les modules suivants sont prêts à être complétés au fil du guide :

```text
app.py                 # Point d’entrée Streamlit
src/data.py            # Chargement et cache des données Sportec
src/models.py          # Schémas du DSL tactique
src/primitives.py      # Primitives déterministes
src/engine.py          # Exécution des règles
src/compiler.py        # Français → DSL
src/viz.py             # Terrain 2D
tests/test_primitives.py
```

Les fichiers de cache seront créés dans `data/cache/` et ne sont pas versionnés.

## Installation

Prérequis : Git for Windows et Python 3.11 à 3.14. Le projet actuel a été
vérifié avec Python 3.14.

```powershell
git clone https://github.com/mehdiben30/patternlense.git
cd patternlense

py -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements-lock.txt
```

Si PowerShell bloque l’activation du venv, exécute cette commande une seule
fois dans la session, puis relance l’activation :

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

`requirements-lock.txt` reproduit les versions utilisées actuellement.
Pour ajouter ou mettre à jour des dépendances intentionnellement, modifie
`requirements.txt`, installe-les, puis régénère le verrouillage :

```powershell
python -m pip freeze > requirements-lock.txt
```

## Configuration locale

La clé OpenAI est locale et ne doit jamais être commitée.

```powershell
Copy-Item .env.example .env
```

Ouvre ensuite `.env` et remplace la valeur de `OPENAI_API_KEY` par ta clé.
Le fichier `.env` est déjà ignoré par Git.

## Lancer l’application

```powershell
streamlit run app.py
```

La page doit afficher **PatternLens** puis « Environnement prêt. ».

## Vérification rapide

```powershell
.\.venv\Scripts\python.exe -m compileall -q app.py src tests
```

## Publier les changements sur GitHub

La branche principale est `main` et le dépôt distant est
`https://github.com/mehdiben30/patternlense.git`.

Connecte Git à GitHub une seule fois sur ce PC :

```powershell
git credential-manager github login --browser --username mehdiben30
```

Après authentification dans le navigateur, publie tes changements :

```powershell
git status
git add <fichiers-a-publier>
git commit -m "Décrire le changement"
git push
```

Pour le premier push d’un nouveau clone ou dépôt local :

```powershell
git branch -M main
git remote add origin https://github.com/mehdiben30/patternlense.git
git push -u origin main
```

Avant un `git add`, vérifie toujours `git status`. Ne publie jamais `.env`,
`.venv/` ni `data/cache/` : ils sont volontairement dans `.gitignore`.
