from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import func
import os
import requests
import time
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'supersecretkey'
from werkzeug.security import generate_password_hash, check_password_hash

def get_condition_multiplier(condition):
    cond = (condition or '').strip().lower()
    if cond in ['near mint', 'nm']:
        return 1.0
    elif cond in ['lightly played', 'lp']:
        return 0.85
    elif cond in ['moderately played', 'mp']:
        return 0.70
    elif cond in ['heavily played', 'hp']:
        return 0.50
    elif cond in ['damaged', 'dmg']:
        return 0.30
    return 1.0

def scoped(model):
    return model.query.filter_by(user_id=session.get('user_id'))

def get_site_admin():
    """Returns the site admin — always the first user who registered (lowest id).
    No username is hardcoded; works correctly on any install."""
    return User.query.order_by(User.id).first()

def is_current_user_site_admin():
    """Returns True if the currently logged-in session user is the site admin."""
    admin = get_site_admin()
    return admin is not None and session.get('user_id') == admin.id

@app.before_request
def check_auth():
    # Allow access to login route, register route, public showcase(s), and static files
    path = request.path
    if path in ['/login', '/register', '/showcases'] or path.startswith('/showcase') or path.startswith('/static/'):
        return
    
    # If no users exist, redirect to registration/setup
    try:
        user_count = User.query.count()
    except Exception:
        user_count = 0
        
    if user_count == 0:
        return redirect(url_for('register'))
        
    if not session.get('user_id'):
        return redirect(url_for('login'))

@app.context_processor
def inject_pending_comments_count():
    is_admin = session.get('user_id') and is_current_user_site_admin()
    if is_admin:
        try:
            pending_count = ShowcaseComment.query.filter_by(is_approved=False).count()
            return {'pending_comments_count': pending_count, 'is_site_admin': True}
        except Exception:
            pass
    return {'pending_comments_count': 0, 'is_site_admin': False}

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'mtg_collection.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    set_code = db.Column(db.String(10), nullable=False)
    collector_number = db.Column(db.String(20))
    rarity = db.Column(db.String(20))
    image_url = db.Column(db.String(255))
    quantity = db.Column(db.Integer, default=1)
    price = db.Column(db.Float, default=0.0)
    is_foil = db.Column(db.Boolean, default=False, server_default='0')
    mana_cost = db.Column(db.String(100), nullable=True)
    cmc = db.Column(db.Integer, default=0, server_default='0')
    type_line = db.Column(db.String(100), nullable=True)
    colors = db.Column(db.String(50), nullable=True)
    is_illegal = db.Column(db.Boolean, default=False, server_default='0')
    condition = db.Column(db.String(50), default='Near Mint', server_default='Near Mint')
    is_modern = db.Column(db.Boolean, default=True, server_default='1')
    is_vintage = db.Column(db.Boolean, default=True, server_default='1')
    released_at = db.Column(db.String(10), nullable=True)
    last_summoned = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
    acquired_price = db.Column(db.Float, nullable=True)
    is_promo = db.Column(db.Boolean, default=False, server_default='0')
    promo_types = db.Column(db.String(255), nullable=True)



    @property
    def is_commander_candidate(self):
        t_lower = (self.type_line or '').lower()
        if 'legendary' in t_lower and 'creature' in t_lower:
            return True
        walker_commanders = [
            "daretti, scrap savant",
            "freyalise, llanowar's fury",
            "nahiri, the lithomancer",
            "ob nixilis of the black oath",
            "teferi, temporal archmage",
            "aminatou, the fateshifter",
            "estrid, the masker",
            "lord windgrace",
            "saheeli, the gifted",
            "grist, the hunger tide",
            "jeska, thrice reborn",
            "tevesh szat, doom of fools"
        ]
        if 'planeswalker' in t_lower and any(w in (self.name or '').lower() for w in walker_commanders):
            return True
        return False

    @property
    def is_in_deck(self):
        return db.session.query(db.exists().where(DeckCard.card_id == self.id)).scalar()

class ReleaseNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(20))
    description = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)

class ValueSnapshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    total_value = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Deck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255))
    format = db.Column(db.String(50), default='Standard')
    cards = db.relationship('DeckCard', backref='deck', cascade='all, delete-orphan')

class DeckCard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    deck_id = db.Column(db.Integer, db.ForeignKey('deck.id'), nullable=False)
    card_id = db.Column(db.Integer, db.ForeignKey('card.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    is_commander = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    
    card = db.relationship('Card')

class Token(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    set_code = db.Column(db.String(10), nullable=True)
    collector_number = db.Column(db.String(20), nullable=True)
    type_line = db.Column(db.String(100), nullable=True)
    image_url = db.Column(db.String(255), nullable=True)
    quantity = db.Column(db.Integer, default=1)

class ArtCard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    set_code = db.Column(db.String(10), nullable=True)
    collector_number = db.Column(db.String(20), nullable=True)
    type_line = db.Column(db.String(100), nullable=True)
    image_url = db.Column(db.String(255), nullable=True)
    quantity = db.Column(db.Integer, default=1)
    price = db.Column(db.Float, default=0.0)

class WishlistCard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    set_code = db.Column(db.String(10), nullable=False)
    collector_number = db.Column(db.String(20))
    rarity = db.Column(db.String(20))
    image_url = db.Column(db.String(255))
    price = db.Column(db.Float, default=0.0)
    is_foil = db.Column(db.Boolean, default=False, server_default='0')
    quantity = db.Column(db.Integer, default=1)

class ShowcaseComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    showcase_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    author_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # NULL = anonymous
    author_name = db.Column(db.String(80), nullable=False, default='Anonymous')
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_approved = db.Column(db.Boolean, default=True, server_default='1')  # guests default False, logged-in True

    showcase_user = db.relationship('User', foreign_keys=[showcase_user_id])
    author_user  = db.relationship('User', foreign_keys=[author_user_id])

def upgrade_database_schema():
    db.create_all()
    inspector = db.inspect(db.engine)
    tables_to_upgrade = ['card', 'deck', 'token', 'art_card', 'value_snapshot', 'wishlist_card']
    for table in tables_to_upgrade:
        if inspector.has_table(table):
            columns = [c['name'] for c in inspector.get_columns(table)]
            if 'user_id' not in columns:
                try:
                    with db.engine.begin() as conn:
                        conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER REFERENCES user(id)"))
                except Exception as e:
                    print(f"Failed to alter table {table} to add user_id: {e}")
            if table == 'card' and 'condition' not in columns:
                try:
                    with db.engine.begin() as conn:
                        conn.execute(db.text("ALTER TABLE card ADD COLUMN condition VARCHAR(50) DEFAULT 'Near Mint'"))
                except Exception as e:
                    print(f"Failed to alter table card to add condition: {e}")
            if table == 'card' and 'is_modern' not in columns:
                try:
                    with db.engine.begin() as conn:
                        conn.execute(db.text("ALTER TABLE card ADD COLUMN is_modern BOOLEAN DEFAULT 1"))
                except Exception as e:
                    print(f"Failed to alter table card to add is_modern: {e}")
            if table == 'card' and 'is_vintage' not in columns:
                try:
                    with db.engine.begin() as conn:
                        conn.execute(db.text("ALTER TABLE card ADD COLUMN is_vintage BOOLEAN DEFAULT 1"))
                except Exception as e:
                    print(f"Failed to alter table card to add is_vintage: {e}")
            if table == 'card' and 'released_at' not in columns:
                try:
                    with db.engine.begin() as conn:
                        conn.execute(db.text("ALTER TABLE card ADD COLUMN released_at VARCHAR(10)"))
                except Exception as e:
                    print(f"Failed to alter table card to add released_at: {e}")
            if table == 'card' and 'last_summoned' not in columns:
                try:
                    with db.engine.begin() as conn:
                        conn.execute(db.text("ALTER TABLE card ADD COLUMN last_summoned DATETIME"))
                except Exception as e:
                    print(f"Failed to alter table card to add last_summoned: {e}")
            if table == 'card' and 'acquired_price' not in columns:
                try:
                    with db.engine.begin() as conn:
                        conn.execute(db.text("ALTER TABLE card ADD COLUMN acquired_price REAL"))
                    with db.engine.begin() as conn:
                        conn.execute(db.text("UPDATE card SET acquired_price = price WHERE acquired_price IS NULL"))
                except Exception as e:
                    print(f"Failed to alter table card to add acquired_price: {e}")
            if table == 'card' and 'is_promo' not in columns:
                try:
                    with db.engine.begin() as conn:
                        conn.execute(db.text("ALTER TABLE card ADD COLUMN is_promo BOOLEAN DEFAULT 0"))
                except Exception as e:
                    print(f"Failed to alter table card to add is_promo: {e}")
            if table == 'card' and 'promo_types' not in columns:
                try:
                    with db.engine.begin() as conn:
                        conn.execute(db.text("ALTER TABLE card ADD COLUMN promo_types VARCHAR(255)"))
                except Exception as e:
                    print(f"Failed to alter table card to add promo_types: {e}")

    # Create showcase_comment table if not present
    if not inspector.has_table('showcase_comment'):
        try:
            with db.engine.begin() as conn:
                conn.execute(db.text("""
                    CREATE TABLE showcase_comment (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        showcase_user_id INTEGER NOT NULL REFERENCES user(id),
                        author_user_id INTEGER REFERENCES user(id),
                        author_name VARCHAR(80) NOT NULL DEFAULT 'Anonymous',
                        body TEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        is_approved INTEGER NOT NULL DEFAULT 1
                    )
                """))
        except Exception as e:
            print(f"Failed to create showcase_comment table: {e}")
    else:
        # Add is_approved column to existing table if missing
        sc_columns = [c['name'] for c in inspector.get_columns('showcase_comment')]
        if 'is_approved' not in sc_columns:
            try:
                with db.engine.begin() as conn:
                    conn.execute(db.text("ALTER TABLE showcase_comment ADD COLUMN is_approved INTEGER NOT NULL DEFAULT 1"))
                    # All existing comments (posted by logged-in users) are already approved
            except Exception as e:
                print(f"Failed to add is_approved to showcase_comment: {e}")


with app.app_context():
    upgrade_database_schema()

def record_snapshot(user_id=None):
    if not user_id:
        user_id = session.get('user_id')
    if not user_id:
        return
    cards = Card.query.filter_by(user_id=user_id).all()
    art_cards = ArtCard.query.filter_by(user_id=user_id).all()
    total_value = sum((c.price or 0.0) * c.quantity for c in cards) + sum((ac.price or 0.0) * ac.quantity for ac in art_cards)
    
    last_snapshot = ValueSnapshot.query.filter_by(user_id=user_id).order_by(ValueSnapshot.timestamp.desc()).first()
    if last_snapshot:
        time_diff = (datetime.utcnow() - last_snapshot.timestamp).total_seconds()
        if time_diff < 60:
            last_snapshot.total_value = total_value
            db.session.commit()
            return
            
    if not last_snapshot or abs(last_snapshot.total_value - total_value) > 0.001:
        snapshot = ValueSnapshot(total_value=total_value, user_id=user_id)
        db.session.add(snapshot)
        db.session.commit()

# --- Routes ---
@app.route('/')
def index():
    cards = scoped(Card).order_by(Card.last_summoned.desc(), Card.id.desc()).all()
    total_value = sum((c.price or 0.0) * c.quantity for c in cards)
    if scoped(ValueSnapshot).count() == 0 and len(cards) > 0:
        record_snapshot()
        
    # Check if price auto-refresh is needed for the day
    needs_auto_refresh = False
    if cards:
        last_updated = get_last_price_update_time()
        if last_updated is None:
            needs_auto_refresh = True
        else:
            if last_updated.date() < datetime.utcnow().date():
                needs_auto_refresh = True

    # Fetch all custom decks for synergy suggestions
    decks = scoped(Deck).all()
    decks_data = []
    for d in decks:
        deck_colors = set()
        for dc in d.cards:
            if dc.card and dc.card.colors:
                for c in dc.card.colors.split(','):
                    deck_colors.add(c.strip().upper())
        decks_data.append({
            'id': d.id,
            'name': d.name,
            'format': d.format,
            'colors': list(deck_colors)
        })
        
    return render_template('index.html', cards=cards, total_value=total_value, decks=decks_data, needs_auto_refresh=needs_auto_refresh)

@app.route('/add', methods=['POST'])
def add_card():
    url = f"https://api.scryfall.com/cards/{request.form['set_code'].lower()}/{request.form['collector_number']}"
    res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"})
    if res.status_code == 200:
        d = res.json()
        set_code = d['set'].upper()
        collector_number = d['collector_number']
        is_foil = 'is_foil' in request.form
        condition = request.form.get('condition', 'Near Mint').strip()
        
        # 1. Look for an exact match (same set, collector #, foil status, and condition)
        existing_card = Card.query.filter_by(set_code=set_code, collector_number=collector_number, is_foil=is_foil, condition=condition, user_id=session.get('user_id')).first()
        
        # 2. Fallback: match by name, set, foil status, and condition for legacy/seeded records that have empty/null collector numbers
        if not existing_card:
            existing_card = Card.query.filter(
                Card.user_id == session.get('user_id'),
                Card.name == d['name'],
                Card.set_code == set_code,
                Card.is_foil == is_foil,
                Card.condition == condition,
                (Card.collector_number == None) | (Card.collector_number == "")
            ).first()
            if existing_card:
                existing_card.collector_number = collector_number  # Update with the correct collector number
 
        if existing_card:
            existing_card.quantity += 1
            existing_card.last_summoned = datetime.utcnow()
            db.session.commit()
            record_snapshot()
            flash(f"Increased quantity of {existing_card.name} ({existing_card.condition}, {'Foil' if is_foil else 'Non-Foil'}) to {existing_card.quantity} (${existing_card.price:.2f} each)!", "success")
        else:
            price_key = 'usd_foil' if is_foil else 'usd'
            base_price = float(d.get('prices', {}).get(price_key) or d.get('prices', {}).get('usd') or 0.0)
            price = base_price * get_condition_multiplier(condition)
            
            mana_cost = d.get('mana_cost', '')
            cmc = int(d.get('cmc', 0.0))
            type_line = d.get('type_line', '')
            colors = ",".join(d.get('colors', []))
            
            legalities = d.get('legalities', {})
            major_formats = [
                'standard', 'pioneer', 'modern', 'legacy', 'vintage', 
                'commander', 'pauper', 'brawl', 'explorer', 'historic', 
                'alchemy', 'timeless', 'oathbreaker'
            ]
            is_illegal = not any(legalities.get(fmt) in ['legal', 'restricted'] for fmt in major_formats)
            is_modern = (legalities.get('modern') in ['legal', 'restricted'])
            is_vintage = (legalities.get('vintage') in ['legal', 'restricted'])
            released_at = d.get('released_at')
            is_promo = d.get('promo', False)
            promo_types_list = d.get('promo_types', [])
            promo_types = ",".join(promo_types_list) if promo_types_list else None
            
            db.session.add(Card(name=d['name'], set_code=set_code, 
                                collector_number=collector_number, 
                                rarity=d['rarity'], image_url=d.get('image_uris', {}).get('normal'), 
                                price=price,
                                acquired_price=price,
                                quantity=1,
                                is_foil=is_foil,
                                mana_cost=mana_cost,
                                cmc=cmc,
                                type_line=type_line,
                                colors=colors,
                                is_illegal=is_illegal,
                                user_id=session.get('user_id'),
                                condition=condition,
                                is_modern=is_modern,
                                is_vintage=is_vintage,
                                released_at=released_at,
                                last_summoned=datetime.utcnow(),
                                is_promo=is_promo,
                                promo_types=promo_types))


            db.session.commit()
            record_snapshot()
            flash(f"Successfully summoned {d['name']} ({condition}, {'Foil' if is_foil else 'Non-Foil'}) for ${price:.2f}!", "success")
    else:
        flash(f"Failed to find card with Set '{request.form['set_code'].upper()}' and Collector Number '{request.form['collector_number']}'.", "error")
    return redirect(url_for('index'))

@app.route('/update_quantity/<int:id>/<action>')
def update_quantity(id, action):
    card = scoped(Card).filter_by(id=id).first_or_404()
    if action == 'add':
        card.quantity += 1
        card.last_summoned = datetime.utcnow()
    elif action == 'sub' and card.quantity > 0:
        card.quantity -= 1
    db.session.commit()
    record_snapshot()
    return redirect(url_for('index'))

@app.route('/update_condition/<int:id>', methods=['POST'])
def update_condition(id):
    card = scoped(Card).filter_by(id=id).first_or_404()
    new_condition = request.form.get('condition', 'Near Mint').strip()
    
    valid_conditions = ['Near Mint', 'Lightly Played', 'Moderately Played', 'Heavily Played', 'Damaged']
    if new_condition not in valid_conditions:
        flash("Invalid card condition selected.", "error")
        return redirect(url_for('card_detail', id=id))
        
    if card.condition != new_condition:
        old_multiplier = get_condition_multiplier(card.condition)
        new_multiplier = get_condition_multiplier(new_condition)
        if old_multiplier > 0:
            card.price = (card.price / old_multiplier) * new_multiplier
            
        matching_card = scoped(Card).filter_by(
            set_code=card.set_code,
            collector_number=card.collector_number,
            is_foil=card.is_foil,
            condition=new_condition
        ).filter(Card.id != card.id).first()
        
        if matching_card:
            matching_card.quantity += card.quantity
            
            deck_cards = DeckCard.query.filter_by(card_id=card.id).all()
            for dc in deck_cards:
                dup_dc = DeckCard.query.filter_by(deck_id=dc.deck_id, card_id=matching_card.id).first()
                if dup_dc:
                    dup_dc.quantity += dc.quantity
                    db.session.delete(dc)
                else:
                    dc.card_id = matching_card.id
                    
            db.session.delete(card)
            db.session.commit()
            record_snapshot()
            flash(f"Merged copies with existing {new_condition} card.", "success")
            return redirect(url_for('card_detail', id=matching_card.id))
        else:
            card.condition = new_condition
            db.session.commit()
            record_snapshot()
            flash(f"Successfully updated condition to {new_condition}.", "success")
            
    return redirect(url_for('card_detail', id=id))

@app.route('/delete/<int:id>')
def delete_card(id):
    card = scoped(Card).filter_by(id=id).first_or_404()
    DeckCard.query.filter_by(card_id=id).delete()
    db.session.delete(card)
    db.session.commit()
    record_snapshot()
    return redirect(url_for('index'))

@app.route('/card/<int:id>')
def card_detail(id):
    card = scoped(Card).filter_by(id=id).first_or_404()
    
    # Query deck associations
    deck_associations = DeckCard.query.filter_by(card_id=card.id).all()
    associated_decks = [{'id': da.deck.id, 'name': da.deck.name, 'quantity': da.quantity, 'format': da.deck.format} for da in deck_associations]
    
    legalities = {}
    scryfall_url = f"https://scryfall.com/card/{card.set_code.lower()}/{card.collector_number}"
    
    url = f"https://api.scryfall.com/cards/{card.set_code.lower()}/{card.collector_number}"
    try:
        res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"}, timeout=5)
        if res.status_code == 200:
            d = res.json()
            legalities = d.get('legalities', {})
            scryfall_url = d.get('scryfall_uri', scryfall_url)
    except Exception:
        pass
        
    return render_template('detail.html', card=card, legalities=legalities, scryfall_url=scryfall_url, decks=associated_decks)

import json

SET_CACHE_FILE = os.path.join(basedir, 'set_size_cache.json')
PRICE_METADATA_FILE = os.path.join(basedir, 'price_update_metadata.json')

def save_last_price_update_time():
    data = {
        'last_updated': datetime.utcnow().isoformat()
    }
    try:
        with open(PRICE_METADATA_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass

def get_last_price_update_time():
    if os.path.exists(PRICE_METADATA_FILE):
        try:
            with open(PRICE_METADATA_FILE, 'r') as f:
                data = json.load(f)
                return datetime.fromisoformat(data.get('last_updated'))
        except Exception:
            pass
    return None

def get_set_total_cards(set_code):
    set_code = set_code.lower()
    
    # Load cache
    cache = {}
    if os.path.exists(SET_CACHE_FILE):
        try:
            with open(SET_CACHE_FILE, 'r') as f:
                cache = json.load(f)
        except Exception:
            pass
            
    if set_code in cache:
        return cache[set_code]
        
    # Query Scryfall
    url = f"https://api.scryfall.com/sets/{set_code}"
    try:
        res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"}, timeout=5)
        if res.status_code == 200:
            d = res.json()
            count = d.get('card_count', 0)
            if count > 0:
                cache[set_code] = count
                # Save cache
                try:
                    with open(SET_CACHE_FILE, 'w') as f:
                        json.dump(cache, f)
                except Exception:
                    pass
                return count
    except Exception:
        pass
        
    return 0

@app.route('/dashboard')
def dashboard():
    record_snapshot()
    history = scoped(ValueSnapshot).order_by(ValueSnapshot.timestamp.asc()).all()
    history_data = [
        {
            'timestamp': h.timestamp.isoformat() + 'Z',
            'value': h.total_value
        }
        for h in history
    ]
    
    total_cards = (db.session.query(func.sum(Card.quantity)).filter(Card.user_id == session.get('user_id')).scalar() or 0) + (db.session.query(func.sum(ArtCard.quantity)).filter(ArtCard.user_id == session.get('user_id')).scalar() or 0)
    total_value = (db.session.query(func.sum(Card.price * Card.quantity)).filter(Card.user_id == session.get('user_id')).scalar() or 0) + sum((ac.price or 0.0) * ac.quantity for ac in scoped(ArtCard).all())
    rarity_stats = db.session.query(Card.rarity, func.sum(Card.quantity)).filter(Card.user_id == session.get('user_id')).group_by(Card.rarity).all()
    
    # Value changes calculations
    now = datetime.utcnow()
    earliest_snapshot = scoped(ValueSnapshot).order_by(ValueSnapshot.timestamp.asc()).first()
    
    def get_value_at_time(target_dt):
        before = scoped(ValueSnapshot).filter(ValueSnapshot.timestamp <= target_dt).order_by(ValueSnapshot.timestamp.desc()).first()
        after = scoped(ValueSnapshot).filter(ValueSnapshot.timestamp >= target_dt).order_by(ValueSnapshot.timestamp.asc()).first()
        if before and after:
            if abs((target_dt - before.timestamp).total_seconds()) < abs((after.timestamp - target_dt).total_seconds()):
                return before.total_value
            return after.total_value
        elif before:
            return before.total_value
        elif after:
            return after.total_value
        return None

    def get_percentage_change(days):
        target_dt = now - timedelta(days=days)
        if not earliest_snapshot or earliest_snapshot.timestamp > target_dt:
            return None
        value_then = get_value_at_time(target_dt)
        if value_then is None or value_then == 0:
            return None
        return ((total_value - value_then) / value_then) * 100

    change_1d = get_percentage_change(1)
    change_1w = get_percentage_change(7)
    change_1m = get_percentage_change(30)
    change_6m = get_percentage_change(180)
    change_1y = get_percentage_change(365)
    
    # Top 5 most valuable cards (excluding basic lands)
    def is_basic_land(c):
        name_lower = (c.name or '').lower().strip()
        basic_lands = {'plains', 'island', 'swamp', 'mountain', 'forest', 'wastes', 'waste'}
        return name_lower in basic_lands

    all_cards = scoped(Card).all()
    non_basic_lands = [c for c in all_cards if not is_basic_land(c)]
    top_valuable_list = sorted(non_basic_lands, key=lambda c: c.price * c.quantity, reverse=True)[:5]
    top_valuable = []
    for c in top_valuable_list:
        card_total = c.price * c.quantity
        share = (card_total / total_value * 100) if total_value > 0 else 0
        top_valuable.append({
            'id': c.id,
            'name': c.name,
            'set_code': c.set_code,
            'image_url': c.image_url,
            'quantity': c.quantity,
            'price': c.price,
            'total_value': card_total,
            'share': share,
            'is_foil': c.is_foil,
            'is_commander_candidate': c.is_commander_candidate
        })
        
    # Top 5 highest quantity non-land cards
    def is_land(c):
        name_lower = c.name.lower()
        basic_lands = ['mountain', 'forest', 'plains', 'island', 'swamp', 'waste']
        return name_lower in basic_lands or 'land' in name_lower
        
    non_lands = [c for c in all_cards if not is_land(c)]
    top_qty_list = sorted(non_lands, key=lambda c: c.quantity, reverse=True)[:5]
    top_qty = []
    for c in top_qty_list:
        top_qty.append({
            'id': c.id,
            'name': c.name,
            'set_code': c.set_code,
            'image_url': c.image_url,
            'quantity': c.quantity,
            'price': c.price,
            'total_value': c.price * c.quantity,
            'is_foil': c.is_foil,
            'is_commander_candidate': c.is_commander_candidate
        })

    # Top 5 biggest losers (absolute value loss since acquisition)
    losers_list = []
    for c in all_cards:
        acq_price = c.acquired_price if c.acquired_price is not None else c.price
        diff = (c.price - acq_price) * c.quantity
        if diff < -0.005:
            losers_list.append((c, diff))
    losers_list = sorted(losers_list, key=lambda x: x[1])[:5]
    
    top_losers = []
    for c, diff in losers_list:
        top_losers.append({
            'id': c.id,
            'name': c.name,
            'set_code': c.set_code,
            'image_url': c.image_url,
            'quantity': c.quantity,
            'price': c.price,
            'acquired_price': c.acquired_price if c.acquired_price is not None else c.price,
            'loss': diff,
            'is_foil': c.is_foil,
            'is_commander_candidate': c.is_commander_candidate
        })

    # Top 5 biggest gainers (absolute value gain since acquisition)
    gainers_list = []
    for c in all_cards:
        acq_price = c.acquired_price if c.acquired_price is not None else c.price
        diff = (c.price - acq_price) * c.quantity
        if diff > 0.005:
            gainers_list.append((c, diff))
    gainers_list = sorted(gainers_list, key=lambda x: x[1], reverse=True)[:5]
    
    top_gainers = []
    for c, diff in gainers_list:
        top_gainers.append({
            'id': c.id,
            'name': c.name,
            'set_code': c.set_code,
            'image_url': c.image_url,
            'quantity': c.quantity,
            'price': c.price,
            'acquired_price': c.acquired_price if c.acquired_price is not None else c.price,
            'gain': diff,
            'is_foil': c.is_foil,
            'is_commander_candidate': c.is_commander_candidate
        })

    # --- NEW: Color stats calculation ---
    color_counts = {'W': 0, 'U': 0, 'B': 0, 'R': 0, 'G': 0, 'Multicolor': 0, 'Colorless': 0}
    for card in all_cards:
        qty = card.quantity
        if not card.colors:
            color_counts['Colorless'] += qty
        else:
            parts = card.colors.split(',')
            if len(parts) > 1:
                color_counts['Multicolor'] += qty
            elif len(parts) == 1:
                c = parts[0].strip().upper()
                if c in color_counts:
                    color_counts[c] += qty
                else:
                    color_counts['Colorless'] += qty
    color_stats = [{'color': k, 'count': v} for k, v in color_counts.items() if v > 0]

    # --- NEW: Set stats calculation (with total USD value per set) ---
    set_mapping = {
        'TMT': 'TMNT (UB)',
        'FIN': 'Final Fantasy (UB)',
        'DFT': 'Aetherdrift',
        'FDN': 'Foundations',
        'FDC': 'Foundations Commander',
        'PIP': 'Fallout (UB)',
        'TDM': 'Tarkir: Dragonstorm',
        '6ED': 'Classic 6th Edition',
        '8ED': '8th Edition',
        '9ED': '9th Edition',
        'ICE': 'Ice Age',
        'INV': 'Invasion',
        'XLN': 'Ixalan',
        'MSC': 'Marvel Super Heroes Commander'
    }
    set_data = {}
    for card in all_cards:
        name = set_mapping.get(card.set_code.upper(), f"Other ({card.set_code.upper()})")
        card_total = card.price * card.quantity
        if name not in set_data:
            set_data[name] = {'count': 0, 'value': 0.0}
        set_data[name]['count'] += card.quantity
        set_data[name]['value'] += card_total
    
    set_stats = [
        {
            'set_name': k,
            'count': v['count'],
            'value': round(v['value'], 2)
        }
        for k, v in set_data.items() if v['count'] > 0
    ]
    set_stats = sorted(set_stats, key=lambda x: x['value'], reverse=True)

    # --- NEW: Foil vs Non-Foil Stats ---
    total_foil = db.session.query(func.sum(Card.quantity)).filter(Card.is_foil == True, Card.user_id == session.get('user_id')).scalar() or 0
    total_non_foil = db.session.query(func.sum(Card.quantity)).filter(Card.is_foil == False, Card.user_id == session.get('user_id')).scalar() or 0
    foil_percentage = (total_foil / total_cards * 100) if total_cards > 0 else 0
    foil_stats = {
        'foil': total_foil,
        'non_foil': total_non_foil,
        'percentage': foil_percentage
    }

    # --- NEW: Card Type Breakdown ---
    type_counts = {
        'Creatures': 0,
        'Lands': 0,
        'Instants': 0,
        'Sorceries': 0,
        'Artifacts': 0,
        'Enchantments': 0,
        'Planeswalkers': 0,
        'Other': 0
    }
    for card in all_cards:
        t = (card.type_line or '').lower()
        qty = card.quantity
        if 'creature' in t:
            type_counts['Creatures'] += qty
        elif 'land' in t:
            type_counts['Lands'] += qty
        elif 'instant' in t:
            type_counts['Instants'] += qty
        elif 'sorcery' in t:
            type_counts['Sorceries'] += qty
        elif 'artifact' in t:
            type_counts['Artifacts'] += qty
        elif 'enchantment' in t:
            type_counts['Enchantments'] += qty
        elif 'planeswalker' in t:
            type_counts['Planeswalkers'] += qty
        else:
            type_counts['Other'] += qty
    type_stats = [{'type_name': k, 'count': v} for k, v in type_counts.items() if v > 0]

    # --- NEW: Recent Additions Feed (Cards, Tokens, Art Cards combined) ---
    recent_cards = scoped(Card).order_by(Card.id.desc()).limit(5).all()
    recent_tokens = scoped(Token).order_by(Token.id.desc()).limit(5).all()
    recent_art = scoped(ArtCard).order_by(ArtCard.id.desc()).limit(5).all()
    
    combined_recent = []
    for c in recent_cards:
        combined_recent.append({
            'name': c.name,
            'type': 'Card',
            'set_code': c.set_code,
            'image_url': c.image_url,
            'details': f"Qty: {c.quantity} · {'Foil' if c.is_foil else 'Normal'}",
            'id': c.id,
            'url': url_for('card_detail', id=c.id)
        })
    for t in recent_tokens:
        combined_recent.append({
            'name': t.name,
            'type': 'Token',
            'set_code': t.set_code,
            'image_url': t.image_url,
            'details': f"Qty: {t.quantity} · Token",
            'id': t.id,
            'url': url_for('list_tokens')
        })
    for a in recent_art:
        combined_recent.append({
            'name': a.name,
            'type': 'Art Card',
            'set_code': a.set_code,
            'image_url': a.image_url,
            'details': f"Qty: {a.quantity} · Art",
            'id': a.id,
            'url': url_for('list_art_cards')
        })
    combined_recent = sorted(combined_recent, key=lambda x: x['id'], reverse=True)[:5]

    # --- NEW: Set Completion and Missing Cards Stats ---
    set_codes = db.session.query(Card.set_code).filter(Card.user_id == session.get('user_id')).distinct().all()
    set_completion = []
    for (s_code,) in set_codes:
        s_code_upper = s_code.upper()
        # Count unique collector numbers owned in this set
        owned_unique = db.session.query(func.count(Card.collector_number.distinct())).filter(Card.set_code == s_code, Card.user_id == session.get('user_id')).scalar() or 0
        total_in_set = get_set_total_cards(s_code)
        
        missing = max(0, total_in_set - owned_unique) if total_in_set > 0 else 0
        completion_rate = (owned_unique / total_in_set * 100) if total_in_set > 0 else 0
        set_name = set_mapping.get(s_code_upper, f"Other ({s_code_upper})")
        
        set_completion.append({
            'set_code': s_code_upper,
            'set_name': set_name,
            'owned_unique': owned_unique,
            'total_in_set': total_in_set,
            'missing': missing,
            'completion_rate': completion_rate
        })
    set_completion = sorted(set_completion, key=lambda x: x['owned_unique'], reverse=True)

    # Fetch all custom decks for synergy suggestions
    decks = Deck.query.all()
    decks_data = []
    for d in decks:
        deck_colors = set()
        for dc in d.cards:
            if dc.card and dc.card.colors:
                for c in dc.card.colors.split(','):
                    deck_colors.add(c.strip().upper())
        decks_data.append({
            'id': d.id,
            'name': d.name,
            'format': d.format,
            'colors': list(deck_colors)
        })
    # Group snapshots by day (UTC)
    daily_snapshots = {}
    for h in history:
        day_str = h.timestamp.date().isoformat()
        daily_snapshots[day_str] = h.total_value
    
    sorted_days = sorted(daily_snapshots.keys())
    daily_history = []
    prev_value = None
    for day in sorted_days:
        val = daily_snapshots[day]
        change_val = None
        change_pct = None
        if prev_value is not None and prev_value != 0:
            change_val = val - prev_value
            change_pct = (change_val / prev_value) * 100
        daily_history.append({
            'date': day,
            'value': val,
            'change_val': change_val,
            'change_pct': change_pct
        })
        prev_value = val
    daily_history.reverse()

    # Check if price auto-refresh is needed for the day
    needs_auto_refresh = False
    if all_cards or scoped(ArtCard).count() > 0:
        last_updated = get_last_price_update_time()
        if last_updated is None:
            needs_auto_refresh = True
        else:
            if last_updated.date() < datetime.utcnow().date():
                needs_auto_refresh = True

    return render_template('dashboard.html', 
        total_cards=total_cards,
        total_value=total_value,
        rarity_stats=rarity_stats,
        history_data=history_data,
        change_1d=change_1d,
        change_1w=change_1w,
        change_1m=change_1m,
        change_6m=change_6m,
        change_1y=change_1y,
        top_valuable=top_valuable,
        top_qty=top_qty,
        top_losers=top_losers,
        top_gainers=top_gainers,
        color_stats=color_stats,
        set_stats=set_stats,
        foil_stats=foil_stats,
        type_stats=type_stats,
        recent_additions=combined_recent,
        set_completion=set_completion,
        last_price_update=get_last_price_update_time(),
        decks=decks_data,
        daily_history=daily_history,
        needs_auto_refresh=needs_auto_refresh)

@app.route('/releases')
def view_releases():
    releases = ReleaseNote.query.all()
    try:
        releases.sort(key=lambda x: [int(v) for v in (x.version or '0').split('.') if v.isdigit()], reverse=True)
    except Exception:
        releases = ReleaseNote.query.order_by(ReleaseNote.date.desc()).all()
    return render_template('releases.html', releases=releases)


@app.route('/refresh_prices')
def refresh_prices():
    cards = scoped(Card).all()
    art_cards = scoped(ArtCard).all()
    
    if not cards and not art_cards:
        flash("No cards in collection to update.", "info")
        return redirect(url_for('dashboard'))
        
    # Build unique set/collector keys and name queries to fetch from Scryfall
    distinct_keys = set()
    playable_names = set()
    for card in cards:
        if card.set_code and card.collector_number:
            distinct_keys.add((card.set_code.lower().strip(), str(card.collector_number).lower().strip()))
            
    for ac in art_cards:
        if ac.set_code and ac.collector_number:
            distinct_keys.add((ac.set_code.lower().strip(), str(ac.collector_number).lower().strip()))
        if ac.name:
            playable_name = ac.name.split(' // ')[0].strip()
            playable_names.add(playable_name.lower().strip())
            
    identifiers = [{'set': key[0], 'collector_number': key[1]} for key in distinct_keys]
    for name in playable_names:
        identifiers.append({'name': name})
    
    # Query Scryfall in chunks of 75 using POST /cards/collection
    scryfall_cards = []
    chunk_size = 75
    for i in range(0, len(identifiers), chunk_size):
        chunk = identifiers[i:i + chunk_size]
        try:
            res = requests.post(
                'https://api.scryfall.com/cards/collection',
                json={'identifiers': chunk},
                headers={'User-Agent': 'MTGTracker/1.0'},
                timeout=15
            )
            if res.status_code == 200:
                scryfall_cards.extend(res.json().get('data', []))
            time.sleep(0.1)  # Respect Scryfall's rate limit
        except Exception as e:
            print("Failed to fetch bulk card prices chunk:", e)
            
    # Map the results to a dictionary of prices
    price_map = {}
    for sc in scryfall_cards:
        s_code = sc.get('set', '').lower().strip()
        coll_num = sc.get('collector_number', '').lower().strip()
        prices = sc.get('prices', {})
        if s_code and coll_num:
            price_map[(s_code, coll_num)] = prices
            
        c_name = sc.get('name', '').lower().strip()
        if c_name:
            price_map[c_name] = prices
            if ' // ' in c_name:
                price_map[c_name.split(' // ')[0].strip()] = prices
        
    # Update standard collection card records
    updated_count = 0
    for card in cards:
        key = (card.set_code.lower().strip(), str(card.collector_number).lower().strip())
        prices = price_map.get(key)
        if prices:
            price_key = 'usd_foil' if card.is_foil else 'usd'
            new_price_str = prices.get(price_key) or prices.get('usd')
            if new_price_str:
                try:
                    card.price = float(new_price_str) * get_condition_multiplier(card.condition)
                    updated_count += 1
                except ValueError:
                    pass
                    
    # Update art card records
    for ac in art_cards:
        prices = None
        if ac.set_code and ac.collector_number:
            key = (ac.set_code.lower().strip(), str(ac.collector_number).lower().strip())
            prices = price_map.get(key)
            
        new_price_str = None
        if prices:
            new_price_str = prices.get('usd') or prices.get('usd_foil')
            
        # Fallback to the corresponding playable card's price if the art card itself has no price on Scryfall
        if not new_price_str and ac.name:
            playable_name = ac.name.split(' // ')[0].strip().lower()
            playable_prices = price_map.get(playable_name)
            if playable_prices:
                new_price_str = playable_prices.get('usd') or playable_prices.get('usd_foil')
                
        if new_price_str:
            try:
                ac.price = float(new_price_str)
                updated_count += 1
            except ValueError:
                pass
                        
    if updated_count > 0:
        db.session.commit()
        record_snapshot()
        save_last_price_update_time()
        flash(f"Successfully refreshed prices for {updated_count} items in your library!", "success")
    else:
        flash("No items had their prices updated.", "info")
        
    return redirect(url_for('dashboard'))

@app.route('/refresh_prices_stream')
def refresh_prices_stream():
    from flask import Response
    user_id = session.get('user_id')
    if not user_id:
        return Response("Unauthorized", status=401)
        
    def generate():
        cards = Card.query.filter_by(user_id=user_id).all()
        art_cards = ArtCard.query.filter_by(user_id=user_id).all()
        
        if not cards and not art_cards:
            yield "data: " + json.dumps({'status': 'complete', 'updated_count': 0, 'message': 'No cards to refresh.'}) + "\n\n"
            return
            
        distinct_keys = set()
        playable_names = set()
        for card in cards:
            if card.set_code and card.collector_number:
                distinct_keys.add((card.set_code.lower().strip(), str(card.collector_number).lower().strip()))
        for ac in art_cards:
            if ac.set_code and ac.collector_number:
                distinct_keys.add((ac.set_code.lower().strip(), str(ac.collector_number).lower().strip()))
            if ac.name:
                playable_name = ac.name.split(' // ')[0].strip()
                playable_names.add(playable_name.lower().strip())
                
        identifiers = [{'set': key[0], 'collector_number': key[1]} for key in distinct_keys]
        for name in playable_names:
            identifiers.append({'name': name})
            
        total_steps = len(identifiers)
        yield "data: " + json.dumps({'status': 'start', 'total': total_steps, 'message': f'Starting refresh of {total_steps} unique printings...'}) + "\n\n"
        
        scryfall_cards = []
        chunk_size = 75
        processed_count = 0
        
        for i in range(0, len(identifiers), chunk_size):
            chunk = identifiers[i:i + chunk_size]
            try:
                res = requests.post(
                    'https://api.scryfall.com/cards/collection',
                    json={'identifiers': chunk},
                    headers={'User-Agent': 'MTGTracker/1.0'},
                    timeout=15
                )
                if res.status_code == 200:
                    scryfall_cards.extend(res.json().get('data', []))
                
                processed_count += len(chunk)
                percent = int((processed_count / total_steps) * 100)
                yield "data: " + json.dumps({'status': 'progress', 'percent': percent, 'processed': processed_count, 'total': total_steps, 'message': f'Downloaded {processed_count} of {total_steps} cards from Scryfall...' }) + "\n\n"
                
                time.sleep(0.1)
            except Exception as e:
                print("Failed to fetch bulk card prices chunk:", e)
                yield "data: " + json.dumps({'status': 'error', 'message': f'Error fetching chunk: {str(e)}'}) + "\n\n"
                
        # Map the results to a dictionary of prices
        price_map = {}
        for sc in scryfall_cards:
            s_code = sc.get('set', '').lower().strip()
            coll_num = sc.get('collector_number', '').lower().strip()
            prices = sc.get('prices', {})
            if s_code and coll_num:
                price_map[(s_code, coll_num)] = prices
            c_name = sc.get('name', '').lower().strip()
            if c_name:
                price_map[c_name] = prices
                if ' // ' in c_name:
                    price_map[c_name.split(' // ')[0].strip()] = prices
                    
        # Update cards
        updated_count = 0
        for card in cards:
            key = (card.set_code.lower().strip(), str(card.collector_number).lower().strip())
            prices = price_map.get(key)
            if prices:
                price_key = 'usd_foil' if card.is_foil else 'usd'
                new_price_str = prices.get(price_key) or prices.get('usd')
                if new_price_str:
                    try:
                        card.price = float(new_price_str) * get_condition_multiplier(card.condition)
                        updated_count += 1
                    except ValueError:
                        pass
                        
        for ac in art_cards:
            prices = None
            if ac.set_code and ac.collector_number:
                key = (ac.set_code.lower().strip(), str(ac.collector_number).lower().strip())
                prices = price_map.get(key)
            new_price_str = None
            if prices:
                new_price_str = prices.get('usd') or prices.get('usd_foil')
            if not new_price_str and ac.name:
                playable_name = ac.name.split(' // ')[0].strip().lower()
                playable_prices = price_map.get(playable_name)
                if playable_prices:
                    new_price_str = playable_prices.get('usd') or playable_prices.get('usd_foil')
            if new_price_str:
                try:
                    ac.price = float(new_price_str)
                    updated_count += 1
                except ValueError:
                    pass
                    
        if updated_count > 0:
            db.session.commit()
            record_snapshot(user_id=user_id)
            save_last_price_update_time()
            
        yield "data: " + json.dumps({'status': 'complete', 'updated_count': updated_count, 'message': f'Success! Refreshed prices for {updated_count} cards.'}) + "\n\n"
        
    from flask import stream_with_context
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/search_scryfall_prints')
def search_scryfall_prints():
    query = request.args.get('q', '').strip()
    set_code = request.args.get('set', '').strip().upper()
    collector_number = request.args.get('num', '').strip().lower()
    
    if not query:
        return jsonify([])
        
    headers = {"User-Agent": "MTGTracker/1.0"}
    exact_print = None
    
    # 1. If set and num are provided, try to fetch the exact print first
    if set_code and collector_number:
        exact_url = f"https://api.scryfall.com/cards/{set_code.lower()}/{collector_number}"
        try:
            res = requests.get(exact_url, headers=headers, timeout=10)
            if res.status_code == 200:
                item = res.json()
                image_url = item.get('image_uris', {}).get('normal') or item.get('card_faces', [{}])[0].get('image_uris', {}).get('normal')
                name = item.get('name', '')
                
                # Fetch owned quantities from local database
                owned_total = db.session.query(func.sum(Card.quantity)).filter(func.lower(Card.name) == func.lower(name), Card.user_id == session.get('user_id')).scalar() or 0
                owned_spec = db.session.query(func.sum(Card.quantity)).filter(
                    func.lower(Card.name) == func.lower(name),
                    func.lower(Card.set_code) == func.lower(set_code),
                    func.lower(Card.collector_number) == func.lower(collector_number),
                    Card.user_id == session.get('user_id')
                ).scalar() or 0
                
                # Fetch wishlist quantities from local database
                wish_total = db.session.query(func.sum(WishlistCard.quantity)).filter(func.lower(WishlistCard.name) == func.lower(name), WishlistCard.user_id == session.get('user_id')).scalar() or 0
                wish_spec = db.session.query(func.sum(WishlistCard.quantity)).filter(
                    func.lower(WishlistCard.name) == func.lower(name),
                    func.lower(WishlistCard.set_code) == func.lower(set_code),
                    func.lower(WishlistCard.collector_number) == func.lower(collector_number),
                    WishlistCard.user_id == session.get('user_id')
                ).scalar() or 0
                
                prices = item.get('prices', {})
                exact_print = {
                    'name': name,
                    'set_code': set_code,
                    'set_name': item.get('set_name'),
                    'collector_number': collector_number,
                    'rarity': item.get('rarity'),
                    'price_usd': prices.get('usd') or '0.0',
                    'price_usd_foil': prices.get('usd_foil') or '0.0',
                    'image_url': image_url,
                    'legalities': item.get('legalities', {}),
                    'released_at': item.get('released_at', ''),
                    'color_identity': item.get('color_identity', []),
                    'colors': item.get('colors', []),
                    'purchase_uris': item.get('purchase_uris', {}),
                    'is_promo': item.get('promo', False),
                    'promo_types': ",".join(item.get('promo_types', [])) if item.get('promo_types') else None,
                    'owned_total': int(owned_total),
                    'owned_spec': int(owned_spec),
                    'wish_total': int(wish_total),
                    'wish_spec': int(wish_spec)
                }
                
                # Update query to match the exact name of the fetched card to ensure we only get its printings
                query = name
        except Exception as e:
            print("Error fetching exact print from Scryfall:", e)
            
    # 2. Search Scryfall for printings
    url = "https://api.scryfall.com/cards/search"
    # If we have set and num, search for the exact name using exact search syntax f'!"{query}"'
    # Otherwise fallback to original syntax
    if set_code and collector_number:
        search_q = f'!"{query}"'
    else:
        search_q = f'"{query}"' if ' ' in query else query
        
    params = {
        'q': search_q,
        'unique': 'prints',
        'include_extras': 'true'
    }
    
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        results = []
        if res.status_code == 200:
            data = res.json().get('data', [])
            for item in data[:60]:  # Increase limit to 60 to fetch more prints for lands/common cards
                image_url = item.get('image_uris', {}).get('normal') or item.get('card_faces', [{}])[0].get('image_uris', {}).get('normal')
                name = item.get('name', '')
                curr_set = item.get('set', '').upper()
                curr_num = item.get('collector_number', '')
                
                # Skip duplicate if this is the exact_print we already fetched
                if exact_print and curr_set == set_code and str(curr_num).lower() == str(collector_number).lower():
                    continue
                    
                # Fetch owned quantities from local database
                owned_total = db.session.query(func.sum(Card.quantity)).filter(func.lower(Card.name) == func.lower(name), Card.user_id == session.get('user_id')).scalar() or 0
                owned_spec = db.session.query(func.sum(Card.quantity)).filter(
                    func.lower(Card.name) == func.lower(name),
                    func.lower(Card.set_code) == func.lower(curr_set),
                    func.lower(Card.collector_number) == func.lower(curr_num),
                    Card.user_id == session.get('user_id')
                ).scalar() or 0
                
                # Fetch wishlist quantities from local database
                wish_total = db.session.query(func.sum(WishlistCard.quantity)).filter(func.lower(WishlistCard.name) == func.lower(name), WishlistCard.user_id == session.get('user_id')).scalar() or 0
                wish_spec = db.session.query(func.sum(WishlistCard.quantity)).filter(
                    func.lower(WishlistCard.name) == func.lower(name),
                    func.lower(WishlistCard.set_code) == func.lower(curr_set),
                    func.lower(WishlistCard.collector_number) == func.lower(curr_num),
                    WishlistCard.user_id == session.get('user_id')
                ).scalar() or 0
                
                results.append({
                    'name': name,
                    'set_code': curr_set,
                    'set_name': item.get('set_name'),
                    'collector_number': curr_num,
                    'rarity': item.get('rarity'),
                    'price_usd': item.get('prices', {}).get('usd') or '0.0',
                    'price_usd_foil': item.get('prices', {}).get('usd_foil') or '0.0',
                    'image_url': image_url,
                    'legalities': item.get('legalities', {}),
                    'released_at': item.get('released_at', ''),
                    'color_identity': item.get('color_identity', []),
                    'colors': item.get('colors', []),
                    'purchase_uris': item.get('purchase_uris', {}),
                    'is_promo': item.get('promo', False),
                    'promo_types': ",".join(item.get('promo_types', [])) if item.get('promo_types') else None,
                    'owned_total': int(owned_total),
                    'owned_spec': int(owned_spec),
                    'wish_total': int(wish_total),
                    'wish_spec': int(wish_spec)
                })
                
        # Prepend exact print if we fetched it
        if exact_print:
            results.insert(0, exact_print)
            
        return jsonify(results)
    except Exception as e:
        print("Scryfall search error:", e)
        
    if exact_print:
        return jsonify([exact_print])
        
    return jsonify([])
 
# --- Wishlist Routes ---
@app.route('/wishlist')
def view_wishlist():
    wishlist = scoped(WishlistCard).order_by(WishlistCard.id.desc()).all()
    total_qty = sum(item.quantity for item in wishlist)
    total_value = sum((item.price or 0.0) * item.quantity for item in wishlist)
    
    # Fetch all custom decks for synergy suggestions
    decks = scoped(Deck).all()
    decks_data = []
    for d in decks:
        deck_colors = set()
        for dc in d.cards:
            if dc.card and dc.card.colors:
                for c in dc.card.colors.split(','):
                    deck_colors.add(c.strip().upper())
        decks_data.append({
            'id': d.id,
            'name': d.name,
            'format': d.format,
            'colors': list(deck_colors)
        })
        
    return render_template('wishlist.html', 
                           wishlist=wishlist, 
                           total_qty=total_qty, 
                           total_value=total_value,
                           decks=decks_data)

@app.route('/wishlist/add', methods=['POST'])
def add_to_wishlist():
    set_code = request.form['set_code'].strip().upper()
    collector_number = request.form['collector_number'].strip()
    is_foil = request.form.get('is_foil') == 'y'
    
    # Check if this card is already in the wishlist
    existing = WishlistCard.query.filter_by(
        set_code=set_code, 
        collector_number=collector_number, 
        is_foil=is_foil,
        user_id=session.get('user_id')
    ).first()
    
    if existing:
        existing.quantity += 1
        db.session.commit()
        flash(f"Increased quantity of {existing.name} in wishlist.", "success")
        return redirect(url_for('view_wishlist'))
        
    # Resolve card from Scryfall API
    url = f"https://api.scryfall.com/cards/{set_code.lower()}/{collector_number}"
    try:
        res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"}, timeout=5)
        if res.status_code == 200:
            d = res.json()
            name = d.get('name')
            rarity = d.get('rarity')
            image_url = d.get('image_uris', {}).get('normal') or d.get('card_faces', [{}])[0].get('image_uris', {}).get('normal')
            
            price_key = 'usd_foil' if is_foil else 'usd'
            price = float(d.get('prices', {}).get(price_key) or d.get('prices', {}).get('usd') or 0.0)
            
            new_item = WishlistCard(
                name=name,
                set_code=set_code,
                collector_number=collector_number,
                rarity=rarity,
                image_url=image_url,
                price=price,
                is_foil=is_foil,
                quantity=1,
                user_id=session.get('user_id')
            )
            db.session.add(new_item)
            db.session.commit()
            flash(f"Successfully added {name} to your wishlist!", "success")
        else:
            flash(f"Error: Card {set_code} #{collector_number} not found on Scryfall.", "error")
    except Exception as e:
        flash(f"Error resolving card: {str(e)}", "error")
        
    return redirect(url_for('view_wishlist'))

@app.route('/wishlist/update_quantity/<int:card_id>/<string:action>')
def update_wishlist_quantity(card_id, action):
    item = scoped(WishlistCard).filter_by(id=card_id).first_or_404()
    if action == 'add':
        item.quantity += 1
    elif action == 'sub':
        item.quantity -= 1
        if item.quantity <= 0:
            db.session.delete(item)
            
    db.session.commit()
    return redirect(url_for('view_wishlist'))

@app.route('/wishlist/delete/<int:card_id>')
def delete_wishlist_card(card_id):
    item = scoped(WishlistCard).filter_by(id=card_id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash("Card removed from wishlist.", "info")
    return redirect(url_for('view_wishlist'))

@app.route('/wishlist/claim/<int:card_id>')
def claim_wishlist_card(card_id):
    item = scoped(WishlistCard).filter_by(id=card_id).first_or_404()
    
    # Add to Card collection model
    # First check if this card is already in the main collection
    existing_collection = Card.query.filter_by(
        set_code=item.set_code,
        collector_number=item.collector_number,
        is_foil=item.is_foil,
        user_id=session.get('user_id')
    ).first()
    
    if existing_collection:
        existing_collection.quantity += item.quantity
    else:
        # Resolve any extra details (like colors, mana cost, cmc, type_line) if available from API
        url = f"https://api.scryfall.com/cards/{item.set_code.lower()}/{item.collector_number}"
        colors_str = None
        mana_cost = None
        cmc = 0
        type_line = None
        is_illegal = False
        try:
            res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"}, timeout=5)
            if res.status_code == 200:
                d = res.json()
                colors = d.get('colors', [])
                colors_str = ','.join(colors) if colors else None
                mana_cost = d.get('mana_cost')
                cmc = int(d.get('cmc', 0))
                type_line = d.get('type_line')
                legalities = d.get('legalities', {})
                major_formats = [
                    'standard', 'pioneer', 'modern', 'legacy', 'vintage', 
                    'commander', 'pauper', 'brawl', 'explorer', 'historic', 
                    'alchemy', 'timeless', 'oathbreaker'
                ]
                is_illegal = not any(legalities.get(fmt) in ['legal', 'restricted'] for fmt in major_formats)
                is_modern = (legalities.get('modern') in ['legal', 'restricted'])
                is_vintage = (legalities.get('vintage') in ['legal', 'restricted'])
                released_at = d.get('released_at')
        except Exception:
            pass
            
        new_card = Card(
            name=item.name,
            set_code=item.set_code,
            collector_number=item.collector_number,
            rarity=item.rarity,
            image_url=item.image_url,
            price=item.price,
            is_foil=item.is_foil,
            quantity=item.quantity,
            colors=colors_str,
            mana_cost=mana_cost,
            cmc=cmc,
            type_line=type_line,
            is_illegal=is_illegal,
            user_id=session.get('user_id'),
            is_modern=is_modern,
            is_vintage=is_vintage,
            released_at=released_at
        )


        db.session.add(new_card)
        
    db.session.delete(item)
    db.session.commit()
    record_snapshot()
    flash(f"Successfully claimed {item.name}! Added to collection and removed from wishlist.", "success")
    return redirect(url_for('view_wishlist'))

# --- Deck Builder Routes ---

@app.route('/decks')
def list_decks():
    decks = scoped(Deck).all()
    
    total_decks = len(decks)
    total_cards = 0
    total_value = 0.0
    format_counts = {}
    
    for d in decks:
        format_counts[d.format] = format_counts.get(d.format, 0) + 1
        for dc in d.cards:
            if dc.card:
                total_cards += dc.quantity
                total_value += (dc.card.price or 0.0) * dc.quantity
            
    return render_template('decks.html', 
                           decks=decks, 
                           total_decks=total_decks,
                           total_cards=total_cards,
                           total_value=round(total_value, 2),
                           format_counts=format_counts)

@app.route('/deck/create', methods=['POST'])
def create_deck():
    name = request.form['name'].strip()
    description = request.form['description'].strip()
    fmt = request.form.get('format', 'Standard')
    if name:
        deck = Deck(name=name, description=description, format=fmt, user_id=session.get('user_id'))
        db.session.add(deck)
        db.session.commit()
        flash(f"Successfully created deck '{name}' ({fmt})!", "success")
    else:
        flash("Deck name cannot be empty.", "error")
    return redirect(url_for('list_decks'))

@app.route('/deck/<int:deck_id>')
def view_deck(deck_id):
    deck = scoped(Deck).filter_by(id=deck_id).first_or_404()
    
    total_cards = sum(dc.quantity for dc in deck.cards if dc.card)
    total_value = sum((dc.card.price or 0.0) * dc.quantity for dc in deck.cards if dc.card)
    
    all_collection_cards = scoped(Card).all()
    available_cards = []
    
    for c in all_collection_cards:
        total_in_decks = db.session.query(func.sum(DeckCard.quantity))\
            .join(Deck)\
            .filter(Deck.user_id == session.get('user_id'), DeckCard.card_id == c.id)\
            .scalar() or 0
        remaining_qty = max(0, c.quantity - total_in_decks)
        available_cards.append({
            'card': c,
            'remaining_qty': remaining_qty
        })
            
    # Calculate deck analytics
    cmc_distribution = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, '7+': 0}
    color_pips = {'W': 0, 'U': 0, 'B': 0, 'R': 0, 'G': 0}
    type_counts = {
        'Creature': 0,
        'Instant': 0,
        'Sorcery': 0,
        'Land': 0,
        'Artifact': 0,
        'Enchantment': 0,
        'Planeswalker': 0,
        'Other': 0
    }
    
    basic_land_names = ['mountain', 'forest', 'plains', 'island', 'swamp', 'waste']
    
    deck_cards_list = []
    for dc in deck.cards:
        card = dc.card
        if not card:
            continue
        qty = dc.quantity
        for _ in range(qty):
            deck_cards_list.append({
                'name': card.name,
                'image_url': card.image_url,
                'is_commander': dc.is_commander
            })
        t_lower = (card.type_line or '').lower()
        name_lower = (card.name or '').lower()
        
        # 1. Type Line breakdown
        is_land = 'land' in t_lower or name_lower in basic_land_names
        if is_land:
            type_counts['Land'] += qty
        elif 'creature' in t_lower:
            type_counts['Creature'] += qty
        elif 'instant' in t_lower:
            type_counts['Instant'] += qty
        elif 'sorcery' in t_lower:
            type_counts['Sorcery'] += qty
        elif 'planeswalker' in t_lower:
            type_counts['Planeswalker'] += qty
        elif 'artifact' in t_lower:
            type_counts['Artifact'] += qty
        elif 'enchantment' in t_lower:
            type_counts['Enchantment'] += qty
        else:
            type_counts['Other'] += qty
            
        # 2. Mana Value (CMC) Distribution (excluding Lands)
        if not is_land:
            c_val = card.cmc or 0
            if c_val >= 7:
                cmc_distribution['7+'] += qty
            elif c_val in cmc_distribution:
                cmc_distribution[c_val] += qty
            else:
                cmc_distribution[0] += qty
                
        # 3. Pip symbol counts
        m_cost = card.mana_cost or ''
        for symbol, key in [('{W}', 'W'), ('{U}', 'U'), ('{B}', 'B'), ('{R}', 'R'), ('{G}', 'G')]:
            pips = m_cost.count(symbol)
            if pips > 0:
                color_pips[key] += pips * qty
                
    return render_template('deck_detail.html', 
                           deck=deck, 
                           total_cards=total_cards, 
                           total_value=total_value, 
                           available_cards=available_cards,
                           cmc_distribution=cmc_distribution,
                           color_pips=color_pips,
                           type_counts=type_counts,
                           deck_cards_list=deck_cards_list)

@app.route('/deck/<int:deck_id>/add', methods=['POST'])
def add_to_deck(deck_id):
    deck = scoped(Deck).filter_by(id=deck_id).first_or_404()
    card_id = int(request.form['card_id'])
    quantity = int(request.form['quantity'])
    
    collection_card = scoped(Card).filter_by(id=card_id).first_or_404()
    
    # 1. Check format legality via Scryfall API
    format_key = deck.format.lower()
    basic_lands = ['mountain', 'forest', 'plains', 'island', 'swamp', 'waste']
    is_basic_land = collection_card.name.lower() in basic_lands
    
    is_legal = True
    is_restricted = False
    
    if not is_basic_land:
        url = f"https://api.scryfall.com/cards/{collection_card.set_code.lower()}/{collection_card.collector_number}"
        try:
            res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"}, timeout=5)
            if res.status_code == 200:
                d = res.json()
                legality = d.get('legalities', {}).get(format_key, 'not_legal')
                if legality == 'not_legal' or legality == 'banned':
                    is_legal = False
                elif legality == 'restricted':
                    is_restricted = True
        except Exception:
            flash("Warning: Could not verify card legality with Scryfall (API offline).", "info")
            
    if not is_legal:
        flash(f"Cannot add {collection_card.name}: It is BANNED or NOT LEGAL in {deck.format}!", "error")
        return redirect(url_for('view_deck', deck_id=deck_id))
        
    # 2. Check quantity limits
    existing_deck_card = DeckCard.query.filter_by(deck_id=deck_id, card_id=card_id).first()
    current_deck_qty = existing_deck_card.quantity if existing_deck_card else 0
    new_deck_qty = current_deck_qty + quantity
    
    # Check against unassigned owned copies (across all decks)
    total_in_decks = db.session.query(func.sum(DeckCard.quantity))\
        .join(Deck)\
        .filter(Deck.user_id == session.get('user_id'), DeckCard.card_id == card_id)\
        .scalar() or 0
    available_qty = max(0, collection_card.quantity - total_in_decks)
    if quantity > available_qty:
        flash(f"Cannot add {quantity} copies. You only have {available_qty} unassigned copies in your collection.", "error")
        return redirect(url_for('view_deck', deck_id=deck_id))
        
    # Enforce format-specific limits
    max_allowed = 4
    if deck.format == 'Commander':
        max_allowed = 1
    elif deck.format == 'Vintage' and is_restricted:
        max_allowed = 1
        
    if not is_basic_land and new_deck_qty > max_allowed:
        if max_allowed == 1:
            flash(f"Cannot add copies. {collection_card.name} is limited to a MAXIMUM of 1 copy in {deck.format} (Singleton / Restricted).", "error")
        else:
            flash(f"Cannot add copies. {collection_card.name} is limited to a MAXIMUM of 4 copies in {deck.format}.", "error")
        return redirect(url_for('view_deck', deck_id=deck_id))
        
    # Proceed to update or add
    if existing_deck_card:
        existing_deck_card.quantity = new_deck_qty
    else:
        db.session.add(DeckCard(deck_id=deck_id, card_id=card_id, quantity=quantity))
    db.session.commit()
    flash(f"Added {quantity}x {collection_card.name} to the deck!", "success")
    return redirect(url_for('view_deck', deck_id=deck_id))

@app.route('/deck/<int:deck_id>/update_quantity/<int:deck_card_id>/<action>')
def update_deck_card_quantity(deck_id, deck_card_id, action):
    dc = DeckCard.query.get_or_404(deck_card_id)
    if dc.deck.user_id != session.get('user_id'):
        abort(404)
    deck = dc.deck
    collection_card = dc.card
    
    if action == 'add':
        # Check collection quantity limit (across all decks)
        total_in_decks = db.session.query(func.sum(DeckCard.quantity))\
            .join(Deck)\
            .filter(Deck.user_id == session.get('user_id'), DeckCard.card_id == collection_card.id)\
            .scalar() or 0
        if total_in_decks >= collection_card.quantity:
            flash(f"Cannot add more. You only own {collection_card.quantity} copies of {collection_card.name} and all are allocated to decks.", "error")
            return redirect(url_for('view_deck', deck_id=deck_id))
            
        # Check format quantity limit
        basic_lands = ['mountain', 'forest', 'plains', 'island', 'swamp', 'waste']
        is_basic_land = collection_card.name.lower() in basic_lands
        
        max_allowed = 4
        if deck.format == 'Commander':
            max_allowed = 1
        elif deck.format == 'Vintage':
            # Check restricted status via Scryfall
            url = f"https://api.scryfall.com/cards/{collection_card.set_code.lower()}/{collection_card.collector_number}"
            try:
                res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"}, timeout=5)
                if res.status_code == 200:
                    d = res.json()
                    if d.get('legalities', {}).get('vintage') == 'restricted':
                        max_allowed = 1
            except Exception:
                pass
                
        if not is_basic_land and dc.quantity >= max_allowed:
            flash(f"Cannot increase. {collection_card.name} is limited to a MAXIMUM of {max_allowed} copies in {deck.format}.", "error")
        else:
            dc.quantity += 1
            db.session.commit()
            flash(f"Increased {collection_card.name} quantity to {dc.quantity}.", "success")
            
    elif action == 'sub':
        if dc.quantity > 1:
            dc.quantity -= 1
            db.session.commit()
            flash(f"Decreased {collection_card.name} quantity to {dc.quantity}.", "success")
        else:
            db.session.delete(dc)
            db.session.commit()
            flash(f"Removed {collection_card.name} from the deck.", "success")
            
    return redirect(url_for('view_deck', deck_id=deck_id))

@app.route('/deck/<int:deck_id>/remove/<int:deck_card_id>')
def remove_from_deck(deck_id, deck_card_id):
    dc = DeckCard.query.get_or_404(deck_card_id)
    if dc.deck.user_id != session.get('user_id'):
        abort(404)
    card_name = dc.card.name
    db.session.delete(dc)
    db.session.commit()
    flash(f"Removed {card_name} from the deck.", "success")
    return redirect(url_for('view_deck', deck_id=deck_id))

@app.route('/deck/<int:deck_id>/toggle_commander/<int:deck_card_id>')
def toggle_commander(deck_id, deck_card_id):
    dc = DeckCard.query.get_or_404(deck_card_id)
    if dc.deck.user_id != session.get('user_id'):
        abort(404)
    if dc.deck_id != deck_id:
        flash("Card does not belong to this deck.", "error")
        return redirect(url_for('view_deck', deck_id=deck_id))
    
    # Check format eligibility
    if dc.deck.format != 'Commander':
        flash(f"Cannot designate a Commander for a {dc.deck.format} deck. Commanders are only supported in the Commander format.", "error")
        return redirect(url_for('view_deck', deck_id=deck_id))
        
    # Check card eligibility when designating as commander
    if not dc.is_commander and not dc.card.is_commander_candidate:
        flash(f"Cannot designate {dc.card.name} as Commander. Card must be a Legendary Creature or a Planeswalker with Commander text.", "error")
        return redirect(url_for('view_deck', deck_id=deck_id))
        
    dc.is_commander = not dc.is_commander
    db.session.commit()
    status = "designated as Commander" if dc.is_commander else "removed from Commander designation"
    flash(f"Updated: {dc.card.name} is now {status}.", "success")
    return redirect(url_for('view_deck', deck_id=deck_id))

@app.route('/deck/delete/<int:deck_id>')
def delete_deck(deck_id):
    deck = scoped(Deck).filter_by(id=deck_id).first_or_404()
    name = deck.name
    db.session.delete(deck)
    db.session.commit()
    flash(f"Deck '{name}' has been deleted.", "success")
    return redirect(url_for('list_decks'))

@app.route('/deck/<int:deck_id>/add_basic_lands', methods=['POST'])
def add_basic_lands(deck_id):
    deck = scoped(Deck).filter_by(id=deck_id).first_or_404()
    land_type = request.form['land_type'].capitalize() # Plains, Island, Swamp, Mountain, Forest
    quantity = int(request.form['quantity'])
    
    land_map = {
        'Plains': {'collector_number': '1', 'name': 'Plains'},
        'Island': {'collector_number': '2', 'name': 'Island'},
        'Swamp': {'collector_number': '3', 'name': 'Swamp'},
        'Mountain': {'collector_number': '4', 'name': 'Mountain'},
        'Forest': {'collector_number': '5', 'name': 'Forest'}
    }
    
    if land_type not in land_map:
        flash("Invalid land type selected.", "error")
        return redirect(url_for('view_deck', deck_id=deck_id))
        
    land_info = land_map[land_type]
    set_code = 'ANA'
    collector_number = land_info['collector_number']
    
    # Check if card already exists in the collection (set ANA, collector_number, non-foil)
    collection_card = Card.query.filter_by(set_code=set_code, collector_number=collector_number, is_foil=False, user_id=session.get('user_id')).first()
    
    if not collection_card:
        # Fetch basic land details from Scryfall API once
        url = f"https://api.scryfall.com/cards/{set_code.lower()}/{collector_number}"
        try:
            res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"}, timeout=5)
            if res.status_code == 200:
                d = res.json()
                collection_card = Card(
                    name=d['name'],
                    set_code=set_code,
                    collector_number=collector_number,
                    rarity=d['rarity'],
                    image_url=d.get('image_uris', {}).get('normal'),
                    price=0.0,
                    quantity=quantity,
                    is_foil=False,
                    mana_cost=d.get('mana_cost', ''),
                    cmc=int(d.get('cmc', 0.0)),
                    type_line=d.get('type_line', ''),
                    colors=",".join(d.get('colors', [])),
                    is_illegal=False,
                    user_id=session.get('user_id'),
                    is_modern=True,
                    is_vintage=True,
                    released_at=d.get('released_at')
                )
                db.session.add(collection_card)
                db.session.commit()
            else:
                # Fallback if Scryfall offline
                collection_card = Card(
                    name=land_info['name'],
                    set_code=set_code,
                    collector_number=collector_number,
                    rarity='common',
                    image_url=None,
                    price=0.0,
                    quantity=quantity,
                    is_foil=False,
                    mana_cost='',
                    cmc=0,
                    type_line=f'Basic Land — {land_info["name"]}',
                    colors='',
                    is_illegal=False,
                    user_id=session.get('user_id'),
                    is_modern=True,
                    is_vintage=True,
                    released_at='1993-08-05'
                )


                db.session.add(collection_card)
                db.session.commit()
        except Exception:
            flash("Failed to add basic lands due to API error.", "error")
            return redirect(url_for('view_deck', deck_id=deck_id))
            
    # Check current quantity in deck
    existing_deck_card = DeckCard.query.filter_by(deck_id=deck_id, card_id=collection_card.id).first()
    current_deck_qty = existing_deck_card.quantity if existing_deck_card else 0
    new_deck_qty = current_deck_qty + quantity
    
    # Commander / Singleton checks don't apply to basic lands! So they are unrestricted.
    # Make sure collection card has enough copies to cover the new total in this deck + other decks
    total_assigned_other_decks = db.session.query(func.sum(DeckCard.quantity)).filter(DeckCard.card_id == collection_card.id, DeckCard.deck_id != deck_id).scalar() or 0
    total_needed = total_assigned_other_decks + new_deck_qty
    
    if collection_card.quantity < total_needed:
        collection_card.quantity = total_needed
        
    if existing_deck_card:
        existing_deck_card.quantity = new_deck_qty
    else:
        db.session.add(DeckCard(deck_id=deck_id, card_id=collection_card.id, quantity=quantity))
        
    db.session.commit()
    record_snapshot()
    flash(f"Successfully summoned {quantity}x {land_info['name']} to the deck!", "success")
    return redirect(url_for('view_deck', deck_id=deck_id))

@app.route('/backfill')
def backfill_cards():
    cards = scoped(Card).filter((Card.type_line == None) | (Card.type_line == '')).all()
    count = 0
    for card in cards:
        time.sleep(0.1) # Rate limit
        url = f"https://api.scryfall.com/cards/{card.set_code.lower()}/{card.collector_number}"
        try:
            res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"}, timeout=5)
            if res.status_code == 200:
                d = res.json()
                card.mana_cost = d.get('mana_cost', '')
                card.cmc = int(d.get('cmc', 0.0))
                card.type_line = d.get('type_line', '')
                card.colors = ",".join(d.get('colors', []))
                
                legalities = d.get('legalities', {})
                major_formats = [
                    'standard', 'pioneer', 'modern', 'legacy', 'vintage', 
                    'commander', 'pauper', 'brawl', 'explorer', 'historic', 
                    'alchemy', 'timeless', 'oathbreaker'
                ]
                card.is_illegal = not any(legalities.get(fmt) in ['legal', 'restricted'] for fmt in major_formats)
                card.is_modern = (legalities.get('modern') in ['legal', 'restricted'])
                card.is_vintage = (legalities.get('vintage') in ['legal', 'restricted'])
                card.released_at = d.get('released_at')
                
                count += 1
        except Exception:
            continue
    if count > 0:
        db.session.commit()
        flash(f"Successfully backfilled details for {count} cards!", "success")
    else:
        flash("All cards already have details populated.", "info")
    return redirect(url_for('index'))

# --- Precon and Deck Import Helpers and Routes ---

def parse_decklist_text(text):
    import re
    lines = text.strip().split('\n')
    cards_list = []
    
    # Regex to capture quantity and name. E.g.:
    # "1 Card Name"
    # "1x Card Name"
    # "1 Card Name (SET) 123"
    # "Card Name" (assumes quantity 1 if no number is found)
    pattern = re.compile(r'^\s*(\d+)\s*x?\s+(.+?)(?:\s+\([A-Za-z0-9]+\)(?:\s+\d+)?)?\s*$')
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('//') or line.startswith('#'):
            continue  # skip comments/empty lines
            
        match = pattern.match(line)
        if match:
            qty = int(match.group(1))
            name = match.group(2).strip()
            cards_list.append({'name': name, 'quantity': qty})
        else:
            # Fallback if no quantity prefix found, e.g. just "Sol Ring"
            name = line.strip()
            if name:
                cards_list.append({'name': name, 'quantity': 1})
                
    return cards_list

def process_imported_cards(deck_name, format_name, description, raw_cards):
    # Create the new Deck
    deck = Deck(name=deck_name, description=description, format=format_name, user_id=session.get('user_id'))
    db.session.add(deck)
    db.session.commit() # Save deck to get deck.id
    
    # Build Scryfall bulk collection request identifiers
    identifiers = []
    for rc in raw_cards:
        ident = {}
        if rc.get('scryfallId'):
            ident['id'] = rc['scryfallId']
        elif rc.get('setCode') and rc.get('number'):
            ident['set'] = rc['setCode'].lower()
            ident['collector_number'] = str(rc['number']).lower()
        else:
            ident['name'] = rc['name']
        identifiers.append(ident)
        
    # Fetch cards details in chunks of 75 from Scryfall bulk endpoint
    scryfall_cards = []
    chunk_size = 75
    for i in range(0, len(identifiers), chunk_size):
        chunk = identifiers[i:i + chunk_size]
        try:
            res = requests.post(
                'https://api.scryfall.com/cards/collection', 
                json={'identifiers': chunk}, 
                headers={'User-Agent': 'MTGTracker/1.0'},
                timeout=15
            )
            if res.status_code == 200:
                scryfall_cards.extend(res.json().get('data', []))
            time.sleep(0.1) # Respect Scryfall rate limits
        except Exception as e:
            print("Failed to fetch bulk card details chunk:", e)
            
    # Create mapping from scryfall ID or name to card details
    scry_map = {}
    for sc in scryfall_cards:
        if sc.get('id'):
            scry_map[sc['id']] = sc
            
        name_lower = sc.get('name', '').lower()
        if name_lower:
            scry_map[name_lower] = sc
            if ' // ' in name_lower:
                parts = name_lower.split(' // ')
                for part in parts:
                    scry_map[part.strip()] = sc
            
        if 'card_faces' in sc and len(sc['card_faces']) > 0:
            for face in sc['card_faces']:
                face_name = face.get('name', '').lower()
                if face_name:
                    scry_map[face_name] = sc
                    
    # Associate cards in collection and add to deck
    for rc in raw_cards:
        sc = None
        if rc.get('scryfallId') and rc['scryfallId'] in scry_map:
            sc = scry_map[rc['scryfallId']]
        elif rc['name'].lower() in scry_map:
            sc = scry_map[rc['name'].lower()]
            
        if not sc:
            # Fallback: check if we can query by name via individual search
            # (only if bulk failed to resolve)
            try:
                url = f"https://api.scryfall.com/cards/named?exact={requests.utils.quote(rc['name'])}"
                res = requests.get(url, headers={'User-Agent': 'MTGTracker/1.0'}, timeout=5)
                if res.status_code == 200:
                    sc = res.json()
                time.sleep(0.1)
            except Exception:
                pass
                
        if not sc:
            print(f"Skipping card {rc['name']} because it could not be resolved on Scryfall.")
            continue
            
        # Check if card is in collection
        db_card = Card.query.filter_by(
            name=sc['name'], 
            set_code=sc['set'].upper(), 
            collector_number=sc['collector_number'],
            user_id=session.get('user_id')
        ).first()
        
        needed_qty = rc['quantity']
        
        if db_card:
            if db_card.quantity < needed_qty:
                db_card.quantity = needed_qty
        else:
            image_url = sc.get('image_uris', {}).get('normal')
            if not image_url and 'card_faces' in sc and len(sc['card_faces']) > 0:
                image_url = sc['card_faces'][0].get('image_uris', {}).get('normal')
                
            legalities = sc.get('legalities', {})
            major_formats = [
                'standard', 'pioneer', 'modern', 'legacy', 'vintage', 
                'commander', 'pauper', 'brawl', 'explorer', 'historic', 
                'alchemy', 'timeless', 'oathbreaker'
            ]
            is_illegal = not any(legalities.get(fmt) in ['legal', 'restricted'] for fmt in major_formats)
            is_modern = (legalities.get('modern') in ['legal', 'restricted'])
            is_vintage = (legalities.get('vintage') in ['legal', 'restricted'])
            released_at = sc.get('released_at')

            db_card = Card(
                name=sc['name'],
                set_code=sc['set'].upper(),
                collector_number=sc['collector_number'],
                rarity=sc['rarity'],
                image_url=image_url,
                price=float(sc.get('prices', {}).get('usd') or 0.0),
                mana_cost=sc.get('mana_cost', ''),
                cmc=int(sc.get('cmc', 0.0)),
                type_line=sc.get('type_line', ''),
                colors=",".join(sc.get('colors', [])),
                quantity=needed_qty,
                is_illegal=is_illegal,
                user_id=session.get('user_id'),
                is_modern=is_modern,
                is_vintage=is_vintage,
                released_at=released_at
            )


            db.session.add(db_card)
            db.session.flush()
            
        # Add to deck
        deck_card = DeckCard(
            deck_id=deck.id,
            card_id=db_card.id,
            quantity=needed_qty
        )
        db.session.add(deck_card)
        
    db.session.commit()
    return deck.id

@app.route('/decks/import')
def import_deck_view():
    decks_list = []
    try:
        res = requests.get('https://mtgjson.com/api/v5/DeckList.json', headers={'User-Agent': 'MTGTracker/1.0'}, timeout=5)
        if res.status_code == 200:
            decks_list = res.json().get('data', [])
            decks_list.sort(key=lambda x: x.get('releaseDate', ''), reverse=True)
    except Exception as e:
        print("Failed to fetch MTGJSON deck list:", e)
        
    return render_template('decks_import.html', decks_list=decks_list)

@app.route('/deck/import/precon', methods=['POST'])
def import_precon():
    file_name = request.form.get('file_name', '').strip()
    if not file_name:
        flash("No precon deck selected.", "error")
        return redirect(url_for('import_deck_view'))
        
    url = f"https://mtgjson.com/api/v5/decks/{file_name}.json"
    try:
        res = requests.get(url, headers={'User-Agent': 'MTGTracker/1.0'}, timeout=10)
        if res.status_code != 200:
            flash(f"Failed to fetch deck from MTGJSON (Status {res.status_code}).", "error")
            return redirect(url_for('import_deck_view'))
            
        deck_data = res.json().get('data', {})
        deck_name = deck_data.get('name', 'Precon Deck')
        deck_type = deck_data.get('type', 'Commander')
        
        deck_format = 'Commander' if 'commander' in deck_type.lower() else 'Standard'
        
        raw_cards = []
        
        commanders = deck_data.get('commander', [])
        for c in commanders:
            raw_cards.append({
                'name': c.get('name'),
                'setCode': c.get('setCode'),
                'number': c.get('number'),
                'scryfallId': c.get('identifiers', {}).get('scryfallId'),
                'quantity': c.get('count', 1),
                'is_commander': True
            })
            
        mainboard = deck_data.get('mainBoard', [])
        for c in mainboard:
            raw_cards.append({
                'name': c.get('name'),
                'setCode': c.get('setCode'),
                'number': c.get('number'),
                'scryfallId': c.get('identifiers', {}).get('scryfallId'),
                'quantity': c.get('count', 1),
                'is_commander': False
            })
            
        deck_id = process_imported_cards(deck_name, deck_format, f"Preconstructed deck {deck_name} imported from MTGJSON.", raw_cards)
        
        if deck_id:
            flash(f"Successfully imported precon '{deck_name}' with {len(raw_cards)} cards into your decks and collection!", "success")
            return redirect(url_for('view_deck', deck_id=deck_id))
        else:
            flash("Failed to import cards into database.", "error")
            
    except Exception as e:
        flash(f"Error importing precon: {str(e)}", "error")
        
    return redirect(url_for('import_deck_view'))

@app.route('/deck/import/text', methods=['POST'])
def import_text_decklist():
    name = request.form.get('name', '').strip() or "Imported Deck"
    fmt = request.form.get('format', 'Commander')
    description = request.form.get('description', '').strip() or "Imported custom decklist."
    decklist_text = request.form.get('decklist', '').strip()
    
    if not decklist_text:
        flash("Decklist content is empty.", "error")
        return redirect(url_for('import_deck_view'))
        
    parsed_cards = parse_decklist_text(decklist_text)
    if not parsed_cards:
        flash("Could not parse any cards from the decklist. Check the format.", "error")
        return redirect(url_for('import_deck_view'))
        
    raw_cards = []
    for c in parsed_cards:
        raw_cards.append({
            'name': c['name'],
            'quantity': c['quantity'],
            'is_commander': False
        })
        
    try:
        deck_id = process_imported_cards(name, fmt, description, raw_cards)
        if deck_id:
            flash(f"Successfully imported custom deck '{name}' with {len(raw_cards)} unique cards into your decks and collection!", "success")
            return redirect(url_for('view_deck', deck_id=deck_id))
        else:
            flash("Failed to import cards into database.", "error")
    except Exception as e:
        flash(f"Error importing custom deck: {str(e)}", "error")
        
    return redirect(url_for('import_deck_view'))

# --- Token Tracker Helpers ---
_sets_cache = None

def get_related_set_codes(set_code):
    global _sets_cache
    set_code = set_code.lower().strip()
    if _sets_cache is None:
        try:
            res = requests.get('https://api.scryfall.com/sets', headers={'User-Agent': 'MTGTracker/1.0'}, timeout=5)
            if res.status_code == 200:
                sets_data = res.json().get('data', [])
                mapping = {}
                for s in sets_data:
                    code = s.get('code', '').lower()
                    parent = s.get('parent_set_code', '').lower()
                    
                    if code:
                        if code not in mapping:
                            mapping[code] = {code}
                        mapping[code].add(code)
                        
                    if parent:
                        if parent not in mapping:
                            mapping[parent] = {parent}
                        mapping[parent].add(code)
                _sets_cache = {k: list(v) for k, v in mapping.items()}
        except Exception:
            pass
            
    related = _sets_cache.get(set_code) if _sets_cache else None
    if not related:
        return [set_code, f"t{set_code}"]
    return related

def get_collector_number_options(cn):
    cn = cn.strip().lower()
    options = {cn}
    import re
    digits = re.findall(r'\d+', cn)
    if digits:
        num = digits[0]
        options.add(num)
        options.add(f"t{num}")
        options.add(f"em{num}")
    return list(options)

# --- Token Tracker Routes ---

@app.route('/tokens')
def list_tokens():
    tokens = scoped(Token).all()
    return render_template('tokens.html', tokens=tokens)

@app.route('/tokens/add', methods=['POST'])
def add_token():
    # Check if this is a set & collector number query
    if 'set_code' in request.form and 'collector_number' in request.form and request.form['set_code'] and request.form['collector_number']:
        set_code = request.form['set_code'].strip().upper()
        collector_number = request.form['collector_number'].strip()
        
        # Build robust scryfall token search query
        sets = get_related_set_codes(set_code)
        cns = get_collector_number_options(collector_number)
        
        set_query = " or ".join([f"set:{s}" for s in sets])
        cn_query = " or ".join([f"cn:{c}" for c in cns])
        
        query = f"is:token ({set_query}) ({cn_query})"
        url = f"https://api.scryfall.com/cards/search?q={requests.utils.quote(query)}"
        
        try:
            res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                results = data.get('data', [])
                if results:
                    # Prioritize token set codes starting with 't'
                    results.sort(key=lambda c: (not c.get('set', '').lower().startswith('t'), c.get('set', '').lower()))
                    d = results[0]
                    
                    type_line = d.get('type_line', '').lower()
                    layout = d.get('layout', '').lower()
                    is_token_card = 'token' in type_line or 'emblem' in type_line or layout == 'token' or layout == 'double_faced_token'
                    
                    if not is_token_card:
                        flash(f"'{d['name']}' is not a token card (it has layout '{layout}' and type '{d.get('type_line')}'). Please summon normal cards from the library page instead.", "error")
                        return redirect(url_for('list_tokens'))
                        
                    existing_token = Token.query.filter_by(
                        name=d['name'], 
                        set_code=d['set'].upper(), 
                        collector_number=d['collector_number'],
                        user_id=session.get('user_id')
                    ).first()
                    
                    image_url = d.get('image_uris', {}).get('normal') or d.get('image_uris', {}).get('large')
                    if not image_url and 'card_faces' in d and len(d['card_faces']) > 0:
                        first_face = d['card_faces'][0]
                        image_url = first_face.get('image_uris', {}).get('normal') or first_face.get('image_uris', {}).get('large')
                    
                    if existing_token:
                        existing_token.quantity += 1
                        db.session.commit()
                        flash(f"Increased quantity of {existing_token.name} token to {existing_token.quantity}!", "success")
                    else:
                        db.session.add(Token(
                            name=d['name'],
                            set_code=d['set'].upper(),
                            collector_number=d['collector_number'],
                            type_line=d.get('type_line', 'Token'),
                            image_url=image_url,
                            quantity=1,
                            user_id=session.get('user_id')
                        ))
                        db.session.commit()
                        flash(f"Successfully summoned {d['name']} token!", "success")
                else:
                    flash(f"No tokens found matching {set_code} #{collector_number}.", "error")
            else:
                flash(f"Failed to find token. Scryfall returned status {res.status_code} for {set_code} #{collector_number}.", "error")
        except Exception as e:
            flash(f"Error fetching token: {str(e)}", "error")
            
    elif 'name' in request.form and request.form['name']:
        # Quick summon path: search by name
        name = request.form['name'].strip()
        query = f"is:token \"{name}\""
        url = f"https://api.scryfall.com/cards/search?q={requests.utils.quote(query)}"
        
        try:
            res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                results = data.get('data', [])
                if results:
                    # Prioritize token set codes starting with 't'
                    results.sort(key=lambda c: (not c.get('set', '').lower().startswith('t'), c.get('set', '').lower()))
                    d = results[0]
                    existing_token = Token.query.filter_by(
                        name=d['name'], 
                        set_code=d['set'].upper(), 
                        collector_number=d['collector_number'],
                        user_id=session.get('user_id')
                    ).first()
                    
                    image_url = d.get('image_uris', {}).get('normal') or d.get('image_uris', {}).get('large')
                    if not image_url and 'card_faces' in d and len(d['card_faces']) > 0:
                        first_face = d['card_faces'][0]
                        image_url = first_face.get('image_uris', {}).get('normal') or first_face.get('image_uris', {}).get('large')
                    
                    if existing_token:
                        existing_token.quantity += 1
                        db.session.commit()
                        flash(f"Increased quantity of {existing_token.name} token to {existing_token.quantity}!", "success")
                    else:
                        db.session.add(Token(
                            name=d['name'],
                            set_code=d['set'].upper(),
                            collector_number=d['collector_number'],
                            type_line=d.get('type_line', 'Token'),
                            image_url=image_url,
                            quantity=1,
                            user_id=session.get('user_id')
                        ))
                        db.session.commit()
                        flash(f"Successfully summoned {d['name']} token!", "success")
                else:
                    flash(f"No tokens found matching '{name}'.", "error")
            else:
                flash(f"Failed to find token matching '{name}'. Status code: {res.status_code}", "error")
        except Exception as e:
            flash(f"Error fetching token matching '{name}': {str(e)}", "error")
    else:
        flash("Invalid token summoning request.", "error")
        
    return redirect(url_for('list_tokens'))

@app.route('/tokens/update_quantity/<int:id>/<action>')
def update_token_quantity(id, action):
    token = scoped(Token).filter_by(id=id).first_or_404()
    if action == 'add':
        token.quantity += 1
    elif action == 'sub' and token.quantity > 0:
        token.quantity -= 1
    db.session.commit()
    return redirect(url_for('list_tokens'))

@app.route('/tokens/delete/<int:id>')
def delete_token(id):
    token = scoped(Token).filter_by(id=id).first_or_404()
    name = token.name
    db.session.delete(token)
    db.session.commit()
    flash(f"Removed {name} token from tracking.", "success")
    return redirect(url_for('list_tokens'))

def get_art_card_price_with_fallback(d):
    price_str = d.get('prices', {}).get('usd') or d.get('prices', {}).get('usd_foil')
    if price_str:
        try:
            return float(price_str)
        except ValueError:
            pass
    # Fallback to playable card price
    name = d.get('name', '')
    if name:
        playable_name = name.split(' // ')[0].strip()
        try:
            res = requests.get(
                f"https://api.scryfall.com/cards/named?exact={requests.utils.quote(playable_name)}",
                headers={"User-Agent": "MTGTracker/1.0"},
                timeout=5
            )
            if res.status_code == 200:
                fallback_data = res.json()
                fallback_price_str = fallback_data.get('prices', {}).get('usd') or fallback_data.get('prices', {}).get('usd_foil')
                if fallback_price_str:
                    return float(fallback_price_str)
        except Exception as e:
            print(f"Error fetching fallback price for {playable_name}: {e}")
    return 0.0

# --- Art Card Tracker Routes ---

@app.route('/art_cards')
def list_art_cards():
    art_cards = scoped(ArtCard).order_by(ArtCard.id.desc()).all()
    total_value = sum((ac.price or 0.0) * ac.quantity for ac in art_cards)
    return render_template('art_cards.html', art_cards=art_cards, total_value=total_value)

@app.route('/art_cards/add', methods=['POST'])
def add_art_card():
    # Check if this is a set & collector number query
    if 'set_code' in request.form and 'collector_number' in request.form and request.form['set_code'] and request.form['collector_number']:
        set_code = request.form['set_code'].strip().upper()
        collector_number = request.form['collector_number'].strip()
        
        # Build robust scryfall art series search query
        sets = get_related_set_codes(set_code)
        cns = get_collector_number_options(collector_number)
        
        set_query = " or ".join([f"set:{s}" for s in sets])
        cn_query = " or ".join([f"cn:{c}" for c in cns])
        
        query = f"is:art_series ({set_query}) ({cn_query})"
        url = f"https://api.scryfall.com/cards/search?q={requests.utils.quote(query)}"
        
        try:
            res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                results = data.get('data', [])
                if results:
                    # Prioritize set codes starting with 'a'
                    results.sort(key=lambda c: (not c.get('set', '').lower().startswith('a'), c.get('set', '').lower()))
                    d = results[0]
                    
                    existing_art = ArtCard.query.filter_by(
                        name=d['name'], 
                        set_code=d['set'].upper(), 
                        collector_number=d['collector_number'],
                        user_id=session.get('user_id')
                    ).first()
                    
                    image_url = d.get('image_uris', {}).get('normal') or d.get('image_uris', {}).get('large')
                    if not image_url and 'card_faces' in d and len(d['card_faces']) > 0:
                        first_face = d['card_faces'][0]
                        image_url = first_face.get('image_uris', {}).get('normal') or first_face.get('image_uris', {}).get('large')
                    
                    price = get_art_card_price_with_fallback(d)
                    if existing_art:
                        existing_art.quantity += 1
                        db.session.commit()
                        record_snapshot()
                        flash(f"Increased quantity of {existing_art.name} art card to {existing_art.quantity}!", "success")
                    else:
                        db.session.add(ArtCard(
                            name=d['name'],
                            set_code=d['set'].upper(),
                            collector_number=d['collector_number'],
                            type_line=d.get('type_line', 'Art Card'),
                            image_url=image_url,
                            quantity=1,
                            price=price,
                            user_id=session.get('user_id')
                        ))
                        db.session.commit()
                        record_snapshot()
                        flash(f"Successfully added {d['name']} art card!", "success")
                else:
                    flash(f"No art cards found matching {set_code} #{collector_number}.", "error")
            else:
                flash(f"Failed to find art card. Scryfall returned status {res.status_code} for {set_code} #{collector_number}.", "error")
        except Exception as e:
            flash(f"Error fetching art card: {str(e)}", "error")
            
    elif 'name' in request.form and request.form['name']:
        # Quick summon path: search by name
        name = request.form['name'].strip()
        query = f"is:art_series \"{name}\""
        url = f"https://api.scryfall.com/cards/search?q={requests.utils.quote(query)}"
        
        try:
            res = requests.get(url, headers={"User-Agent": "MTGTracker/1.0"}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                results = data.get('data', [])
                if results:
                    # Prioritize set codes starting with 'a'
                    results.sort(key=lambda c: (not c.get('set', '').lower().startswith('a'), c.get('set', '').lower()))
                    d = results[0]
                    existing_art = ArtCard.query.filter_by(
                        name=d['name'], 
                        set_code=d['set'].upper(), 
                        collector_number=d['collector_number'],
                        user_id=session.get('user_id')
                    ).first()
                    
                    image_url = d.get('image_uris', {}).get('normal') or d.get('image_uris', {}).get('large')
                    if not image_url and 'card_faces' in d and len(d['card_faces']) > 0:
                        first_face = d['card_faces'][0]
                        image_url = first_face.get('image_uris', {}).get('normal') or first_face.get('image_uris', {}).get('large')
                    
                    price = get_art_card_price_with_fallback(d)
                    if existing_art:
                        existing_art.quantity += 1
                        db.session.commit()
                        record_snapshot()
                        flash(f"Increased quantity of {existing_art.name} art card to {existing_art.quantity}!", "success")
                    else:
                        db.session.add(ArtCard(
                            name=d['name'],
                            set_code=d['set'].upper(),
                            collector_number=d['collector_number'],
                            type_line=d.get('type_line', 'Art Card'),
                            image_url=image_url,
                            quantity=1,
                            price=price,
                            user_id=session.get('user_id')
                        ))
                        db.session.commit()
                        record_snapshot()
                        flash(f"Successfully added {d['name']} art card!", "success")
                else:
                    flash(f"No art cards found matching '{name}'.", "error")
            else:
                flash(f"Failed to find art card matching '{name}'. Status code: {res.status_code}", "error")
        except Exception as e:
            flash(f"Error fetching art card matching '{name}': {str(e)}", "error")
    else:
        flash("Invalid art card request.", "error")
        
    return redirect(url_for('list_art_cards'))

@app.route('/art_cards/update_quantity/<int:id>/<action>')
def update_art_card_quantity(id, action):
    art_card = scoped(ArtCard).filter_by(id=id).first_or_404()
    if action == 'add':
        art_card.quantity += 1
    elif action == 'sub' and art_card.quantity > 0:
        art_card.quantity -= 1
    db.session.commit()
    record_snapshot()
    return redirect(url_for('list_art_cards'))

@app.route('/art_cards/delete/<int:id>')
def delete_art_card(id):
    art_card = scoped(ArtCard).filter_by(id=id).first_or_404()
    name = art_card.name
    db.session.delete(art_card)
    db.session.commit()
    record_snapshot()
    flash(f"Removed {name} art card from tracking.", "success")
    return redirect(url_for('list_art_cards'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('index'))
        else:
            error = 'Invalid username or password. Please try again.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('user_id'):
        return redirect(url_for('index'))
    
    is_first_user = (User.query.count() == 0)
    error = None
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not username or not password:
            error = "Username and password cannot be empty."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif User.query.filter_by(username=username).first():
            error = "Username is already taken."
        else:
            user = User(username=username, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            
            # If this is the first user, auto-assign any existing orphaned records to them
            if is_first_user:
                first_user_id = user.id
                Card.query.filter(Card.user_id == None).update({Card.user_id: first_user_id})
                Deck.query.filter(Deck.user_id == None).update({Deck.user_id: first_user_id})
                Token.query.filter(Token.user_id == None).update({Token.user_id: first_user_id})
                ArtCard.query.filter(ArtCard.user_id == None).update({ArtCard.user_id: first_user_id})
                ValueSnapshot.query.filter(ValueSnapshot.user_id == None).update({ValueSnapshot.user_id: first_user_id})
                WishlistCard.query.filter(WishlistCard.user_id == None).update({WishlistCard.user_id: first_user_id})
                db.session.commit()
            
            session['user_id'] = user.id
            session['username'] = user.username
            flash("Account created and vault unlocked!", "success")
            return redirect(url_for('index'))
            
    return render_template('register.html', error=error, is_first_user=is_first_user)

@app.route('/guide')
def view_guide():
    return render_template('guide.html')

@app.route('/formats')
@app.route('/rules')
def view_formats():
    return render_template('formats.html')

@app.route('/settings', methods=['GET', 'POST'])
def view_settings():
    if not session.get('user_id'):
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        user = User.query.get(session['user_id'])
        
        # Verify current password
        if not check_password_hash(user.password_hash, current_password):
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('view_settings'))
            
        if not new_password:
            flash('New password cannot be empty.', 'error')
            return redirect(url_for('view_settings'))
            
        if new_password != confirm_password:
            flash('New passwords do not match.', 'error')
            return redirect(url_for('view_settings'))
            
        # Save password
        try:
            user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash('Vault password updated successfully!', 'success')
        except Exception as e:
            flash(f'Failed to save new password: {str(e)}', 'error')
            
        return redirect(url_for('view_settings'))
        
    return render_template('settings.html')

@app.route('/settings/backup_db')
def backup_db():
    if not session.get('user_id'):
        return redirect(url_for('login'))
        
    from flask import send_file
    db_path = os.path.join(basedir, 'mtg_collection.db')
    if not os.path.exists(db_path):
        flash("Database file not found.", "error")
        return redirect(url_for('view_settings'))
        
    return send_file(db_path, as_attachment=True, download_name='mtg_collection_backup.db')

@app.route('/settings/import_db', methods=['POST'])
def import_db():
    if not session.get('user_id'):
        return redirect(url_for('login'))
        
    if 'db_file' not in request.files:
        flash('No file selected.', 'error')
        return redirect(url_for('view_settings'))
        
    file = request.files['db_file']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('view_settings'))
        
    if file:
        import sqlite3
        import shutil
        
        temp_path = os.path.join(basedir, 'temp_import.db')
        file.save(temp_path)
        
        try:
            conn = sqlite3.connect(temp_path)
            cursor = conn.cursor()
            
            tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            required_tables = ['user', 'card', 'deck', 'deck_card']
            
            missing_tables = [t for t in required_tables if t not in tables]
            if missing_tables:
                conn.close()
                os.remove(temp_path)
                flash(f"Invalid database backup. Missing required tables: {', '.join(missing_tables)}", "error")
                return redirect(url_for('view_settings'))
                
            conn.close()
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            flash(f"Failed to validate database backup: {str(e)}", "error")
            return redirect(url_for('view_settings'))
            
        db_path = os.path.join(basedir, 'mtg_collection.db')
        try:
            db.session.remove()
            db.engine.dispose()
            
            shutil.copy2(temp_path, db_path)
            os.remove(temp_path)
            
            session.clear()
            flash("Database restored successfully! Please log in again.", "success")
            return redirect(url_for('login'))
            
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            flash(f"Failed to restore database: {str(e)}", "error")
            return redirect(url_for('view_settings'))
            
    return redirect(url_for('view_settings'))

def get_github_token_from_git():
    try:
        import subprocess
        result = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=3)
        url = result.stdout.strip()
        if url and "@" in url:
            part = url.split("://")[1].split("@")[0]
            if ":" in part:
                return part.split(":")[0]
            return part
    except Exception:
        pass
    return None

@app.route('/api/check_updates')
def check_updates():
    if not session.get('user_id'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    latest_local = ReleaseNote.query.order_by(ReleaseNote.id.desc()).first()
    local_version = latest_local.version if latest_local else '0.0.0'
    
    headers = {"User-Agent": "MTGTracker/1.0"}
    token = os.environ.get("GITHUB_TOKEN") or get_github_token_from_git()
    if token:
        headers["Authorization"] = f"token {token}"
        
    try:
        res = requests.get('https://api.github.com/repos/jpbell/mtg-collection-tracker/releases/latest', headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            gh_tag = data.get('tag_name', '').replace('v', '').strip()
            
            # Compare local vs github version
            local_parts = [int(p) for p in local_version.split('.') if p.isdigit()]
            gh_parts = [int(p) for p in gh_tag.split('.') if p.isdigit()]
            
            max_len = max(len(local_parts), len(gh_parts))
            local_parts += [0] * (max_len - len(local_parts))
            gh_parts += [0] * (max_len - len(gh_parts))
            
            update_available = gh_parts > local_parts
            
            return jsonify({
                'update_available': update_available,
                'latest_version': gh_tag,
                'current_version': local_version,
                'description': data.get('body', '')
            })
    except Exception as e:
        print("Failed to check GitHub releases:", e)
        
    return jsonify({
        'update_available': False,
        'latest_version': local_version,
        'current_version': local_version
    })

@app.route('/api/trigger_update', methods=['POST'])
def trigger_update():
    if not session.get('user_id'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    import subprocess
    try:
        subprocess.run(["git", "fetch", "origin"], check=True, timeout=15)
        branch_res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=True)
        branch = branch_res.stdout.strip() or 'main'
        
        pull_res = subprocess.run(["git", "pull", "origin", branch], capture_output=True, text=True, check=True)
        upgrade_database_schema()
        
        return jsonify({
            'success': True,
            'message': f"Successfully updated codebase from origin/{branch}!",
            'git_output': pull_res.stdout.strip()
        })
    except subprocess.CalledProcessError as e:
        print("Git pull failed:", e.stderr)
        return jsonify({
            'success': False,
            'message': f"Git command failed: {e.stderr or str(e)}"
        }), 500
    except Exception as e:
        print("Update error:", e)
        return jsonify({
            'success': False,
            'message': f"Failed to perform update: {str(e)}"
        }), 500

@app.route('/showcases')
def showcase_index():
    """Public index listing every user's showcase with preview stats."""
    users = User.query.order_by(User.id).all()
    showcases = []
    for u in users:
        all_cards = Card.query.filter_by(user_id=u.id).all()
        total_val = sum((c.price or 0.0) * c.quantity for c in all_cards)
        card_count = sum(c.quantity for c in all_cards)
        vintage_top = Card.query.filter(
            Card.user_id == u.id,
            Card.is_vintage == True,
            Card.released_at < '2003-07-28'
        ).order_by(Card.price.desc()).first()
        modern_top = Card.query.filter_by(user_id=u.id, is_modern=True).order_by(Card.price.desc()).first()
        top_card = vintage_top or modern_top
        comment_count = ShowcaseComment.query.filter_by(showcase_user_id=u.id, is_approved=True).count()
        pending_comment_count = ShowcaseComment.query.filter_by(showcase_user_id=u.id, is_approved=False).count()
        showcases.append({
            'user': u,
            'total_value': total_val,
            'card_count': card_count,
            'top_card': top_card,
            'comment_count': comment_count,
            'pending_comment_count': pending_comment_count,
        })
    # Sort by total value descending
    showcases.sort(key=lambda x: x['total_value'], reverse=True)
    return render_template('showcase_index.html', showcases=showcases)


@app.route('/showcase')
@app.route('/showcase/<username>')
def view_showcase(username=None):
    if username:
        user = User.query.filter_by(username=username).first_or_404()
    else:
        if session.get('user_id'):
            user = User.query.get(session['user_id'])
        else:
            # Fallback to the first user if not logged in and no username specified
            user = User.query.first()
            if not user:
                return "No user showcases available.", 404
    
    vintage_cards = Card.query.filter(Card.user_id == user.id, Card.is_vintage == True, Card.released_at < '2003-07-28').order_by(Card.price.desc()).limit(5).all()
    vintage_ids = [c.id for c in vintage_cards]
    
    modern_cards = Card.query.filter_by(user_id=user.id, is_modern=True).filter(~Card.id.in_(vintage_ids) if vintage_ids else True).order_by(Card.price.desc()).limit(10).all()
    
    showcase_cards = list(vintage_cards) + list(modern_cards)
    total_qty = sum(c.quantity for c in showcase_cards)
    total_value = sum((c.price or 0.0) * c.quantity for c in showcase_cards)
    
    # Calculate concentration percentage of total collection value
    all_cards = Card.query.filter_by(user_id=user.id).all()
    total_collection_val = sum((c.price or 0.0) * c.quantity for c in all_cards)
    
    concentration = 0.0
    if total_collection_val > 0:
        concentration = (total_value / total_collection_val) * 100

    # Only show approved comments publicly; site admin also sees pending queue
    is_admin = is_current_user_site_admin()

    approved_comments = ShowcaseComment.query.filter_by(
        showcase_user_id=user.id, is_approved=True
    ).order_by(ShowcaseComment.created_at.desc()).all()

    pending_comments = []
    if is_admin:
        pending_comments = ShowcaseComment.query.filter_by(
            showcase_user_id=user.id, is_approved=False
        ).order_by(ShowcaseComment.created_at.asc()).all()

    return render_template('showcase.html',
                           vintage_cards=vintage_cards,
                           modern_cards=modern_cards,
                           total_value=total_value,
                           total_qty=total_qty,
                           concentration=concentration,
                           showcase_user=user,
                           comments=approved_comments,
                           pending_comments=pending_comments,
                           is_site_admin=is_admin)


@app.route('/showcase/<username>/comment', methods=['POST'])
def post_showcase_comment(username):
    showcase_user = User.query.filter_by(username=username).first_or_404()
    body = (request.form.get('body') or '').strip()
    if not body:
        flash('Comment cannot be empty.', 'error')
        return redirect(url_for('view_showcase', username=username))
    if len(body) > 1000:
        flash('Comment is too long (max 1000 characters).', 'error')
        return redirect(url_for('view_showcase', username=username))

    if session.get('user_id'):
        author = User.query.get(session['user_id'])
        author_name = author.username if author else 'Anonymous'
        author_id = session['user_id']
        is_approved = True  # logged-in users are auto-approved
    else:
        raw_name = (request.form.get('author_name') or '').strip()
        author_name = raw_name[:80] if raw_name else 'Anonymous'
        author_id = None
        is_approved = False  # guests require site admin approval

    comment = ShowcaseComment(
        showcase_user_id=showcase_user.id,
        author_user_id=author_id,
        author_name=author_name,
        body=body,
        is_approved=is_approved
    )
    db.session.add(comment)
    db.session.commit()
    if is_approved:
        flash('Comment posted!', 'success')
    else:
        flash('Your comment has been submitted and is awaiting approval.', 'success')
    return redirect(url_for('view_showcase', username=username) + '#comments')


@app.route('/showcase/<username>/comment/<int:comment_id>/delete', methods=['POST'])
def delete_showcase_comment(username, comment_id):
    """Delete a comment — allowed by the showcase owner or the comment author."""
    comment = ShowcaseComment.query.get_or_404(comment_id)
    showcase_user = User.query.filter_by(username=username).first_or_404()
    uid = session.get('user_id')
    if not uid:
        abort(403)
    # Only the showcase owner OR the comment's author may delete it
    if uid != showcase_user.id and uid != comment.author_user_id:
        abort(403)
    db.session.delete(comment)
    db.session.commit()
    flash('Comment removed.', 'success')
    return redirect(url_for('view_showcase', username=username) + '#comments')


@app.route('/showcase/<username>/comment/<int:comment_id>/approve', methods=['POST'])
def approve_showcase_comment(username, comment_id):
    """Approve a pending guest comment — only the site admin (first registered user) can do this."""
    if not is_current_user_site_admin():
        abort(403)
    comment = ShowcaseComment.query.get_or_404(comment_id)
    comment.is_approved = True
    db.session.commit()
    flash(f'Comment by "{comment.author_name}" approved.', 'success')
    return redirect(url_for('view_showcase', username=username) + '#comments')


@app.route('/showcase/<username>/comment/<int:comment_id>/reject', methods=['POST'])
def reject_showcase_comment(username, comment_id):
    """Reject (delete) a pending guest comment — only the site admin (first registered user) can do this."""
    if not is_current_user_site_admin():
        abort(403)
    comment = ShowcaseComment.query.get_or_404(comment_id)
    db.session.delete(comment)
    db.session.commit()
    flash('Comment rejected and removed.', 'success')
    return redirect(url_for('view_showcase', username=username) + '#comments')


if __name__ == '__main__': app.run(host='0.0.0.0', debug=True)
