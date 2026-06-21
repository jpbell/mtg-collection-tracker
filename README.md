# 🔮 The Magicvault

**The Magicvault** is a premium, feature-rich web application for cataloging Magic: The Gathering collections, building decks, tracking battlefield tokens/art cards, analyzing deck demographics, and simulating playtest starting hands.

Designed with a sleek, responsive dark glassmorphism user interface and backed by a lightweight SQLite database, The Magicvault integrates directly with the **Scryfall API** for card detail resolution/pricing and **MTGJSON** for official preconstructed deck data.

---

## ⚡ Key Features

### 1. 🗂️ Collection Inventory Tracker
* **Card Summoning**: Add cards using Set Code and Collector Number, fetching pricing, artwork, mana costs, and colors instantly.
* **Foil Options**: Separate tracking for standard and Foil printings with set-specific pricing.
* **Estimated Value & Analytics**: Tracks unique items and dynamic USD value of the collection over time using price snapshots.
* **Robust Advanced Search**: Scryfall-like search filters. Type syntax queries (e.g. `type:creature`, `color:w`, `cmc>=5`, `is:foil`, `is:commander`) or general keywords (e.g. `rare instant`) to filter collection instantly client-side.

### 2. 🛡️ Deck Builder & Legality Verifier
* **Collection-Limited Building**: Restricts deck composition to cards physically in your collection. Tells you how many copies are available vs. currently committed.
* **Format Legality Check**: Queries Scryfall to verify deck legality (Standard, Modern, Commander, Pioneer, Legacy, Pauper, Vintage). Banned or illegal cards cannot be added.
* **Basic Land Summoner**: Instantly summon basic lands (Plains, Island, Swamp, Mountain, Forest) in bulk. It automatically adds the lands to your collection with a $0.00 price tag to preserve collection financial statistics.

### 3. 📥 Preconstructed & Custom Deck Importers
* **MTGJSON Precon Database**: Search from over **2,700+** official preconstructed decks (Commander precons, Challenger decks, early theme decks) from MTG history. Rebuilds and imports the deck with a single click.
* **Custom Text Decklist Parser**: Paste standard formats (e.g., `1 Sol Ring` or `1x Elesh Norn`) to import them.
* **Bulk Scryfall Resolution**: Resolves cards in chunks of 75 using Scryfall's bulk POST `/cards/collection` endpoint, processing full 100-card decks in seconds.
* **Collection Synchronization**: Automatically adds imported deck cards to your physical collection database or increases quantities to cover the deck's requirements.

### 4. 🪙 Token & Art Card Trackers
* **战场 Token Tracker**: Summons and catalogs physical tokens by Set Code and Collector Number.
* **🎨 Art Series Tracker**: Tracks MTG Art Series collectibles.
* **Advanced Query Resolution**: Dynamically maps parent sets to token/art sets (e.g., searching `WOE #15` resolves `TWOE #15` *Monster // Sorcerer* token and `AWOE #15` *Spiteful Hexmage* art card) and prioritizes set identifiers. Includes double-faced face-specific image fallback checks.

### 5. 📊 Deck Analytics & Playtest Simulator
* **Curve & Pips Chart**: Displays a vertical bar chart of spell CMC curve and counts colored mana symbols (`{W}`, `{U}`, etc.).
* **Type Breakdown**: Proportional progress bars indicating Creatures, Lands, Instants, Sorceries, Artifacts, Enchantments, and Planeswalkers.
* **Playtest Simulator**: Shuffles the deck and draws a starting hand of 7 cards. Features a functional **Mulligan** button (draws one card fewer recursively) and a **Reset** button to start over.

---

## 🛠️ Tech Stack
* **Backend**: Flask (Python 3)
* **ORM / Database**: SQLAlchemy (SQLite)
* **Migrations**: Flask-Migrate (Alembic)
* **API Integrations**: Scryfall REST API, MTGJSON file server
* **Frontend**: HTML5, Vanilla JavaScript, CSS Custom Properties (Sleek glassmorphism theme)

---

## 🚀 Setup & Run Instructions

### 1. Prerequisite Checklist
* Python 3.8 or higher installed on your system.
* Active internet connection (required for MTGJSON lists and Scryfall card queries).

### 2. Environment Installation
Clone or navigate to the workspace directory, then configure a virtual environment:
```bash
# Create a virtual environment named 'venv'
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Install all required Python packages
pip install -r requirements.txt
```

### 3. Database Initialization
Prepare the SQLite database schema by upgrading it to the latest migration head:
```bash
# Apply database migration revisions
flask db upgrade
```

### 4. Running the Server
Launch the Flask development server:
```bash
# Run using Flask command line
flask run

# OR run directly via python
python3 app.py
```
Open your browser and navigate to `http://127.0.0.1:5000` to start managing your library!

---

## 📁 File Structure
```
├── app.py                  # Main Flask application, routes, models, and API helpers
├── requirements.txt        # Python package dependencies and version requirements
├── mtg_collection.db       # SQLite local database (generated at database upgrade)
├── migrations/             # Database migration version files (Alembic/Flask-Migrate)
└── templates/              # Jinja2 HTML templates
    ├── base.html           # Main document shell, custom styling, and global navbar
    ├── index.html          # Collection inventory view and card summoner panel
    ├── detail.html         # Individual card details and collection specs
    ├── decks.html          # Deck list dashboard and simple creation form
    ├── deck_detail.html    # Deck builder editor, curve analytics, and hand simulator
    ├── decks_import.html   # Precon database search and text copy-paste importers
    ├── tokens.html         # Token inventory tracker view
    ├── art_cards.html      # Art series collector tracking view
    ├── dashboard.html      # Global collection valuation charts and leaderboards
    └── releases.html       # Application version release notes
```

---

## 👤 Created By
* **Joshua Bell** - [joshuapbell.com](https://joshuapbell.com)
