import flet as ft
import sqlite3
import uuid
import os
import shutil
import base64
import tempfile
from datetime import datetime

# Tenta importar FPDF
try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False

# --- CONFIGURAÇÃO DE CAMINHOS ---
USER_HOME = os.path.expanduser("~")
DB_FILE = os.path.join(USER_HOME, "retro_collection_v3.db")
IMAGE_DIR = os.path.join(USER_HOME, "retro_images")

# Cores
COLOR_BG = "#1E1E1E"        
COLOR_SURFACE = "#303030"   
COLOR_PRIMARY = "#3584e4"   
COLOR_TEXT = "#ffffff"
COLOR_ERROR = "#ff7b7b"
COLOR_SUCCESS = "#2ec27e"
COLOR_WARNING = "#e5a50a"

# --- FUNÇÃO GLOBAL ---
def formatar_moeda(val):
    try: return f"R$ {float(val):,.2f}"
    except: return "R$ 0.00"

# --- CLASSE PDF ---
if HAS_FPDF:
    class PDF(FPDF):
        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 7)
            self.set_text_color(128)
            self.cell(0, 10, f'Pagina {self.page_no()} - Gerado pelo App Retro-Estante', 0, 0, 'C')

# ===================================================================
# ===== BANCO DE DADOS ==============================================
# ===================================================================
class DatabaseManager:
    def __init__(self):
        self.conn = None
        if not os.path.exists(IMAGE_DIR):
            try: os.makedirs(IMAGE_DIR)
            except: pass 
        self.init_db()

    def connect(self):
        self.conn = sqlite3.connect(DB_FILE)
        self.conn.row_factory = sqlite3.Row
        return self.conn.cursor()

    def close(self):
        if self.conn: self.conn.close()

    def init_db(self):
        try:
            c = self.connect()
            for table in ["Systems", "Categories", "Regions", "Authenticities"]:
                c.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, name TEXT UNIQUE)")
            
            c.execute("""CREATE TABLE IF NOT EXISTS Items (
                id TEXT PRIMARY KEY, name TEXT, category_id TEXT, system_id TEXT, authenticity_id TEXT, region_id TEXT,
                has_box INTEGER, has_manual INTEGER, condition_notes TEXT, storage_location TEXT,
                purchase_price REAL, market_value REAL, selling_price REAL, is_for_sale INTEGER,
                image_filename TEXT, last_modified TIMESTAMP, is_deleted INTEGER DEFAULT 0,
                status TEXT DEFAULT 'Active', exit_date TEXT, exit_reason TEXT
            )""")
            
            try: c.execute("SELECT status FROM Items LIMIT 1")
            except:
                columns = ["status TEXT DEFAULT 'Active'", "exit_date TEXT", "exit_reason TEXT"]
                for col in columns:
                    try: c.execute(f"ALTER TABLE Items ADD COLUMN {col}")
                    except: pass

            c.execute("""CREATE TABLE IF NOT EXISTS ItemImages (
                id TEXT PRIMARY KEY, item_id TEXT, filename TEXT,
                FOREIGN KEY(item_id) REFERENCES Items(id)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS MaintenanceLogs (
                id TEXT PRIMARY KEY, item_id TEXT, log_date TEXT, description TEXT,
                FOREIGN KEY(item_id) REFERENCES Items(id)
            )""")
            self.conn.commit()
        except Exception as e:
            print(f"Erro Fatal Init DB: {e}")
        finally:
            self.close()

    # --- Consultas ---
    def get_systems_with_count(self):
        c = self.connect()
        try:
            sql = """SELECT s.id, s.name, COUNT(i.id) as qtd FROM Systems s JOIN Items i ON i.system_id = s.id WHERE i.is_deleted = 0 AND (i.status IS NULL OR i.status = 'Active') GROUP BY s.id, s.name ORDER BY s.name"""
            c.execute(sql); res = c.fetchall()
        except: res = []
        self.close(); return res

    def search_items(self, query):
        c = self.connect()
        try:
            sql = """SELECT i.id, i.name, s.name as sys_name, i.status FROM Items i LEFT JOIN Systems s ON i.system_id = s.id WHERE i.is_deleted = 0 AND (i.status IS NULL OR i.status = 'Active') AND i.name LIKE ? ORDER BY i.name LIMIT 50"""
            c.execute(sql, (f'%{query}%',)); res = c.fetchall()
        except: res = []
        self.close(); return res

    def get_items_filtered(self, system_id, category_id):
        c = self.connect()
        try:
            sql = """SELECT i.id, i.name, i.image_filename, i.status FROM Items i WHERE i.is_deleted = 0 AND (i.status IS NULL OR i.status = 'Active') AND i.system_id = ? AND i.category_id = ? ORDER BY i.name"""
            c.execute(sql, (system_id, category_id)); res = c.fetchall()
        except: res = []
        self.close(); return res

    def get_items_for_sale_report(self):
        c = self.connect()
        try:
            sql = """SELECT i.name, s.name as sys_name, c.name as cat_name, i.selling_price, i.condition_notes FROM Items i LEFT JOIN Systems s ON i.system_id = s.id LEFT JOIN Categories c ON i.category_id = c.id WHERE i.is_deleted = 0 AND (i.status IS NULL OR i.status = 'Active') AND i.is_for_sale = 1 ORDER BY s.name, i.name"""
            c.execute(sql); res = c.fetchall()
        except: res = []
        self.close(); return res

    # --- Imagens Multiplas ---
    def get_images(self, item_id):
        c = self.connect(); 
        try: c.execute("SELECT * FROM ItemImages WHERE item_id=?", (item_id,)); res = c.fetchall()
        except: res = []
        self.close(); return res

    def add_image(self, item_id, filename):
        imgs = self.get_images(item_id)
        if len(imgs) >= 5: return False, "Limite de 5 imagens."
        try: c = self.connect(); c.execute("INSERT INTO ItemImages (id, item_id, filename) VALUES (?,?,?)", (str(uuid.uuid4()), item_id, filename)); self.conn.commit(); self.close(); return True, "OK"
        except Exception as e: return False, str(e)

    def delete_image(self, img_id):
        try: c = self.connect(); c.execute("DELETE FROM ItemImages WHERE id=?", (img_id,)); self.conn.commit(); self.close(); return True
        except: return False

    # --- Baixa e Logs ---
    def write_off_item(self, item_id, reason, details):
        try:
            c = self.connect()
            c.execute("UPDATE Items SET status = 'Removed', exit_date = ?, exit_reason = ? WHERE id = ?", (datetime.now().strftime("%d/%m/%Y"), f"{reason}: {details}", item_id))
            self.conn.commit(); self.close(); return True, "OK"
        except Exception as e: return False, str(e)

    def add_log(self, item_id, description):
        if not description: return False, "Vazio"
        try:
            c = self.connect(); c.execute("INSERT INTO MaintenanceLogs (id, item_id, log_date, description) VALUES (?,?,?,?)", (str(uuid.uuid4()), item_id, datetime.now().strftime("%d/%m/%Y"), description))
            self.conn.commit(); self.close(); return True, "OK"
        except Exception as e: return False, str(e)

    def get_logs(self, item_id):
        c = self.connect()
        try: c.execute("SELECT * FROM MaintenanceLogs WHERE item_id=? ORDER BY rowid DESC", (item_id,)); res = c.fetchall()
        except: res = []
        self.close(); return res

    def delete_log(self, log_id):
        try: c = self.connect(); c.execute("DELETE FROM MaintenanceLogs WHERE id=?", (log_id,)); self.conn.commit(); self.close(); return True
        except: return False

    # --- CRUD Basico ---
    def get_list_raw(self, table):
        c = self.connect(); c.execute(f"SELECT id, name FROM {table} ORDER BY name"); res = c.fetchall(); self.close(); return res
    def get_list_options(self, table):
        return [ft.dropdown.Option(key=row['id'], text=row['name']) for row in self.get_list_raw(table)]
    def add_aux(self, table, name):
        try: c = self.connect(); c.execute(f"INSERT INTO {table} (id, name) VALUES (?,?)", (str(uuid.uuid4()), name.strip())); self.conn.commit(); self.close(); return True, "OK"
        except Exception as e: self.close(); return False, str(e)
    def update_aux(self, table, uid, name):
        try: c = self.connect(); c.execute(f"UPDATE {table} SET name=? WHERE id=?", (name.strip(), uid)); self.conn.commit(); self.close(); return True, "OK"
        except Exception as e: return False, str(e)
    def delete_aux(self, table, uid):
        try: c = self.connect(); c.execute(f"DELETE FROM {table} WHERE id=?", (uid,)); self.conn.commit(); self.close(); return True
        except: return False
    def delete_item_permanent(self, uid):
        try: c = self.connect(); c.execute("UPDATE Items SET is_deleted = 1 WHERE id = ?", (uid,)); self.conn.commit(); self.close(); return True
        except: return False
    def get_item(self, uid):
        c = self.connect(); c.execute("SELECT * FROM Items WHERE id=?", (uid,)); row = c.fetchone(); self.close(); return row
    def save_item(self, data, uid=None):
        c = self.connect()
        try:
            if not uid:
                new_uid = str(uuid.uuid4())
                c.execute("""INSERT INTO Items (id, name, system_id, category_id, region_id, authenticity_id, storage_location, purchase_price, market_value, selling_price, is_for_sale, condition_notes, has_box, has_manual, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'Active')""", (new_uid, data['name'], data['system_id'], data['category_id'], data['region_id'], data['authenticity_id'], data['storage_location'], data['purchase_price'], data['market_value'], data['selling_price'], data['is_for_sale'], data['condition_notes'], data['has_box'], data['has_manual']))
                res_id = new_uid
            else:
                c.execute("""UPDATE Items SET name=?, system_id=?, category_id=?, region_id=?, authenticity_id=?, storage_location=?, purchase_price=?, market_value=?, selling_price=?, is_for_sale=?, condition_notes=?, has_box=?, has_manual=? WHERE id=?""", (data['name'], data['system_id'], data['category_id'], data['region_id'], data['authenticity_id'], data['storage_location'], data['purchase_price'], data['market_value'], data['selling_price'], data['is_for_sale'], data['condition_notes'], data['has_box'], data['has_manual'], uid))
                res_id = uid
            self.conn.commit()
            return True, res_id
        except Exception as e:
            return False, str(e)
        finally:
            self.close()
    def get_stats(self):
        c = self.connect(); c.execute("SELECT COUNT(*), SUM(purchase_price), SUM(market_value) FROM Items WHERE is_deleted=0 AND (status IS NULL OR status='Active')"); res = c.fetchone(); self.close(); return res

db = DatabaseManager()

# ===================================================================
# ===== APP PRINCIPAL ===============================================
# ===================================================================

def main(page: ft.Page):
    page.window.width = 390; page.window.height = 844; page.window.resizable = False 
    page.title = "Retro-Estante"; page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = COLOR_BG; page.padding = 0
    page.theme = ft.Theme(color_scheme=ft.ColorScheme(primary=COLOR_PRIMARY, background=COLOR_BG, surface=COLOR_SURFACE))
    
    icon_path = os.path.join("assets", "icon.png")
    if os.path.exists(icon_path): page.window_icon = icon_path
    
    page.update()

    if page.platform in [ft.PagePlatform.WINDOWS, ft.PagePlatform.LINUX, ft.PagePlatform.MACOS]:
        page.add(ft.Container(content=ft.Row([ft.Text("12:30", size=12, color="#a0a0a0"), ft.Row([ft.Icon(ft.Icons.WIFI, size=14, color="#a0a0a0"), ft.Icon(ft.Icons.BATTERY_FULL, size=14, color="#a0a0a0")], spacing=5)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), bgcolor="#000000", height=30, padding=ft.padding.symmetric(horizontal=15)))

    # Globais
    editing_id = None; picked_image_path = None; aux_context = {"table": "", "title": ""}; nav_context = {"sys_id": None, "sys_name": "", "cat_id": None, "cat_name": ""}
    image_preview_ref = ft.Ref[ft.Image](); btn_image_text_ref = ft.Ref[ft.ElevatedButton]()

    def on_file_picked(e: ft.FilePickerResultEvent):
        nonlocal picked_image_path
        if e.files:
            picked_image_path = e.files[0].path
            try:
                with open(picked_image_path, "rb") as image_file: encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
                if image_preview_ref.current: image_preview_ref.current.src_base64 = encoded_string; image_preview_ref.current.src = ""; image_preview_ref.current.update()
                if btn_image_text_ref.current: btn_image_text_ref.current.text = "Imagem Carregada!"; btn_image_text_ref.current.update()
            except Exception as ex: print(f"Erro img: {ex}")

    file_picker = ft.FilePicker(on_result=on_file_picked); page.overlay.append(file_picker)
    save_file_picker = ft.FilePicker(); page.overlay.append(save_file_picker)

    def show_snack(msg, color=ft.Colors.GREEN_400):
        page.snack_bar = ft.SnackBar(content=ft.Text(str(msg), color=ft.Colors.WHITE), bgcolor=color)
        page.snack_bar.open = True; page.update()

    # --- VIEWS ---
    def view_home():
        txt_search = ft.TextField(hint_text="Buscar item...", prefix_icon=ft.Icons.SEARCH, border_radius=20, height=40, text_size=14, content_padding=10, on_change=lambda e: on_search(e.control.value))
        lv_content = ft.ListView(expand=True, spacing=5, padding=10)

        def render_systems():
            systems = db.get_systems_with_count(); lv_content.controls.clear()
            if not systems: lv_content.controls.append(ft.Column([ft.Icon(ft.Icons.VIDEOGAME_ASSET_OFF, size=60, color="grey"), ft.Text("Coleção Vazia", color="grey")], alignment="center", horizontal_alignment="center"))
            for s in systems: lv_content.controls.append(ft.ListTile(leading=ft.Icon(ft.Icons.GAMEPAD, color=COLOR_PRIMARY, size=30), title=ft.Text(s['name'], weight="bold"), subtitle=ft.Text(f"{s['qtd']} ativos"), trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT, color="grey"), bgcolor=COLOR_SURFACE, shape=ft.RoundedRectangleBorder(radius=10), on_click=lambda e, sid=s['id'], sn=s['name']: go_to_categories(sid, sn)))

        def render_search_results(query):
            results = db.search_items(query); lv_content.controls.clear()
            if not results: lv_content.controls.append(ft.Container(content=ft.Text("Nada encontrado", color="grey"), alignment=ft.alignment.center, padding=20))
            else:
                lv_content.controls.append(ft.Text(f"Encontrados: {len(results)}", color="grey", size=12))
                for row in results:
                    icon, col = (ft.Icons.ATTACH_MONEY, COLOR_SUCCESS) if row['is_for_sale'] else (ft.Icons.VIDEOGAME_ASSET, ft.Colors.WHITE)
                    lv_content.controls.append(ft.ListTile(leading=ft.Icon(icon, color=col), title=ft.Text(row['name'], weight="bold"), subtitle=ft.Text(row['sys_name'] or "-", color="grey"), bgcolor=COLOR_SURFACE, shape=ft.RoundedRectangleBorder(radius=8), on_click=lambda e, uid=row['id']: go_to_edit(uid)))

        def on_search(query):
            if len(query) >= 3: render_search_results(query)
            else: render_systems()
            lv_content.update()

        render_systems()
        return ft.View("/", controls=[ft.AppBar(title=ft.Text("Minha Coleção"), bgcolor=COLOR_SURFACE, actions=[ft.IconButton(ft.Icons.BAR_CHART, on_click=lambda _: page.go("/report")), ft.IconButton(ft.Icons.SETTINGS, on_click=lambda _: page.go("/settings"))]), ft.Container(padding=ft.padding.only(left=10, right=10, top=5), content=txt_search), ft.Container(expand=True, content=lv_content, padding=10)], floating_action_button=ft.FloatingActionButton(icon=ft.Icons.ADD, bgcolor=COLOR_PRIMARY, on_click=lambda _: go_to_add()), bgcolor=COLOR_BG)

    def view_categories():
        cats = db.get_categories_in_system(nav_context["sys_id"]); lv = ft.ListView(expand=True, spacing=5, padding=10)
        for c in cats: lv.controls.append(ft.ListTile(leading=ft.Icon(ft.Icons.FOLDER, color=ft.Colors.ORANGE_400, size=30), title=ft.Text(c['name'], weight="bold"), subtitle=ft.Text(f"{c['qtd']} itens"), trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT, color="grey"), bgcolor=COLOR_SURFACE, shape=ft.RoundedRectangleBorder(radius=10), on_click=lambda e, cid=c['id'], cn=c['name']: go_to_items(cid, cn)))
        return ft.View("/categories", controls=[ft.AppBar(leading=ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: page.go("/")), title=ft.Text(nav_context["sys_name"]), bgcolor=COLOR_SURFACE), ft.Container(expand=True, content=lv, padding=10)], floating_action_button=ft.FloatingActionButton(icon=ft.Icons.ADD, bgcolor=COLOR_PRIMARY, on_click=lambda _: go_to_add()), bgcolor=COLOR_BG)

    def view_item_list():
        items = db.get_items_filtered(nav_context["sys_id"], nav_context["cat_id"]); lv = ft.ListView(expand=True, spacing=5, padding=10)
        for row in items:
            icon, col = (ft.Icons.ATTACH_MONEY, COLOR_SUCCESS) if row['is_for_sale'] else (ft.Icons.VIDEOGAME_ASSET, ft.Colors.WHITE)
            lv.controls.append(ft.ListTile(leading=ft.Icon(icon, color=col), title=ft.Text(row['name'], weight="bold"), subtitle=ft.Text("À Venda" if row['is_for_sale'] else "Na coleção", color="grey"), bgcolor=COLOR_SURFACE, shape=ft.RoundedRectangleBorder(radius=8), on_click=lambda e, uid=row['id']: go_to_edit(uid)))
        return ft.View("/items", controls=[ft.AppBar(leading=ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: page.go("/categories")), title=ft.Text(nav_context["cat_name"]), bgcolor=COLOR_SURFACE), ft.Container(expand=True, content=lv, padding=10)], floating_action_button=ft.FloatingActionButton(icon=ft.Icons.ADD, bgcolor=COLOR_PRIMARY, on_click=lambda _: go_to_add()), bgcolor=COLOR_BG)

    def view_form():
        nonlocal editing_id
        txt_name = ft.TextField(label="Nome", border_radius=10)
        dd_sys = ft.Dropdown(label="Sistema", options=db.get_list_options("Systems"), border_radius=10, expand=True)
        dd_cat = ft.Dropdown(label="Categoria", options=db.get_list_options("Categories"), border_radius=10, expand=True)
        dd_reg = ft.Dropdown(label="Região", options=db.get_list_options("Regions"), border_radius=10, expand=True)
        dd_auth = ft.Dropdown(label="Autenticidade", options=db.get_list_options("Authenticities"), border_radius=10, expand=True)
        txt_storage = ft.TextField(label="Localização", icon=ft.Icons.INVENTORY_2, border_radius=10)
        chk_box = ft.Switch(label="Caixa?"); chk_manual = ft.Switch(label="Manual?")
        txt_buy = ft.TextField(label="Pago (R$)", keyboard_type=ft.KeyboardType.NUMBER, expand=True, border_radius=10)
        txt_mkt = ft.TextField(label="Mercado (R$)", keyboard_type=ft.KeyboardType.NUMBER, expand=True, border_radius=10)
        chk_sale = ft.Switch(label="À Venda?", on_change=lambda e: setattr(txt_sell, 'disabled', not chk_sale.value) or txt_sell.update())
        txt_sell = ft.TextField(label="Venda (R$)", keyboard_type=ft.KeyboardType.NUMBER, border_radius=10, disabled=True)
        txt_notes = ft.TextField(label="Notas", multiline=True, min_lines=3, border_radius=10)
        
        images_row = ft.Row(scroll=ft.ScrollMode.HIDDEN, spacing=10)
        def refresh_images():
            if not editing_id: return
            imgs = db.get_images(editing_id); images_row.controls.clear()
            images_row.controls.append(ft.Container(content=ft.Icon(ft.Icons.ADD_A_PHOTO, color="grey"), width=100, height=100, bgcolor="black", border_radius=10, on_click=lambda _: file_picker.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)))
            for img in imgs:
                fp = os.path.join(IMAGE_DIR, img['filename'])
                if os.path.exists(fp): images_row.controls.append(ft.Stack([ft.Image(src=fp, width=100, height=100, fit=ft.ImageFit.COVER, border_radius=10), ft.IconButton(ft.Icons.CLOSE, icon_color="red", right=0, top=0, on_click=lambda e, iid=img['id']: del_image(iid))], width=100, height=100))
            images_row.update()
        def del_image(img_id):
            if db.delete_image(img_id): refresh_images()
        def on_image_picked(e: ft.FilePickerResultEvent):
            if not editing_id: show_snack("Salve o item primeiro para adicionar fotos.", COLOR_WARNING); return
            if e.files:
                fpath = e.files[0].path
                try: new_name=f"{uuid.uuid4()}{os.path.splitext(fpath)[1] or '.jpg'}"; shutil.copy(fpath, os.path.join(IMAGE_DIR, new_name)); ok,m=db.add_image(editing_id, new_name); 
                except Exception as ex: show_snack(f"Erro: {ex}", COLOR_ERROR); return
                if ok: refresh_images()
        file_picker.on_result = on_image_picked

        txt_log = ft.TextField(label="Descrição", expand=True)
        lv_logs = ft.Column(spacing=10)
        def refresh_logs(ui=True):
            if not editing_id: return
            logs = db.get_logs(editing_id); lv_logs.controls.clear()
            for l in logs:
                lv_logs.controls.append(ft.Container(content=ft.Column([ft.Row([ft.Text(l['log_date'], weight="bold", color=COLOR_PRIMARY), ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=20, icon_color="red", on_click=lambda e, lid=l['id']: del_log(lid))], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), ft.Text(l['description'])]), bgcolor=ft.Colors.BLACK12, padding=10, border_radius=5))
            if ui: lv_logs.update()
        def add_log(e):
            ok, msg = db.add_log(editing_id, txt_log.value)
            if editing_id and txt_log.value and ok: txt_log.value=""; txt_log.update(); refresh_logs(); show_snack("Log Add")
            else: show_snack(msg, COLOR_ERROR)
        def del_log(lid): 
            if db.delete_log(lid): refresh_logs()

        def save_click(e):
            if not txt_name.value: show_snack("Nome Obrigatório!", COLOR_ERROR); return
            data = {'name': txt_name.value, 'system_id': dd_sys.value, 'category_id': dd_cat.value, 'region_id': dd_reg.value, 'authenticity_id': dd_auth.value, 'storage_location': txt_storage.value, 'purchase_price': float(txt_buy.value or 0), 'market_value': float(txt_mkt.value or 0), 'selling_price': float(txt_sell.value or 0), 'is_for_sale': 1 if chk_sale.value else 0, 'condition_notes': txt_notes.value, 'has_box': 1 if chk_box.value else 0, 'has_manual': 1 if chk_manual.value else 0}
            
            ok, result = db.save_item(data, editing_id)
            if ok:
                new_id = result
                if not editing_id: editing_id = new_id; show_snack("Item criado! Adicione fotos.", COLOR_SUCCESS); refresh_images(); page.update()
                else: show_snack("Item atualizado!", COLOR_SUCCESS); page.go("/")
            else: show_snack(f"Erro ao salvar: {result}", COLOR_ERROR)

        dlg_baixa_reason = ft.Dropdown(label="Motivo", options=[ft.dropdown.Option("Venda"), ft.dropdown.Option("Troca"), ft.dropdown.Option("Doação"), ft.dropdown.Option("Descarte"), ft.dropdown.Option("Outro")])
        dlg_baixa_obs = ft.TextField(label="Detalhes")
        def confirm_baixa(e):
            if not dlg_baixa_reason.value: return
            ok, msg = db.write_off_item(editing_id, dlg_baixa_reason.value, dlg_baixa_obs.value)
            if ok: show_snack("Baixado!", COLOR_SUCCESS); page.close(dlg_baixa); page.go("/")
            else: show_snack(f"Erro: {msg}", COLOR_ERROR)
        dlg_baixa = ft.AlertDialog(title=ft.Text("Dar Baixa"), content=ft.Column([ft.Text("O item sairá da coleção."), dlg_baixa_reason, dlg_baixa_obs], tight=True), actions=[ft.TextButton("Cancelar", on_click=lambda e: page.close(dlg_baixa)), ft.TextButton("CONFIRMAR", on_click=confirm_baixa)])
        def open_baixa(e): page.open(dlg_baixa)
        def delete_permanent(e): 
            if editing_id: db.delete_item_permanent(editing_id); page.go("/")

        if not editing_id:
            if nav_context["sys_id"]: dd_sys.value = nav_context["sys_id"]
            if nav_context["cat_id"]: dd_cat.value = nav_context["cat_id"]
            images_row.controls.append(ft.Text("Salve o item para adicionar fotos", color="grey"))
        else:
            r = db.get_item(editing_id)
            if r:
                txt_name.value=r['name']; dd_sys.value=r['system_id']; dd_cat.value=r['category_id']; dd_reg.value=r['region_id']; dd_auth.value=r['authenticity_id']; txt_storage.value=r['storage_location']
                txt_buy.value=str(r['purchase_price'] or 0); txt_mkt.value=str(r['market_value'] or 0); txt_sell.value=str(r['selling_price'] or 0)
                chk_box.value=bool(r['has_box']); chk_manual.value=bool(r['has_manual']); chk_sale.value=bool(r['is_for_sale']); txt_sell.disabled=not chk_sale.value
                txt_notes.value=r['condition_notes']
                refresh_images(); refresh_logs(ui=False)

        actions_bar = []
        if editing_id: actions_bar = [ft.PopupMenuButton(items=[ft.PopupMenuItem(text="Dar Baixa", icon=ft.Icons.ARCHIVE, on_click=open_baixa), ft.PopupMenuItem(text="Excluir", icon=ft.Icons.DELETE_FOREVER, on_click=delete_permanent)])]

        return ft.View("/form", controls=[
            ft.AppBar(title=ft.Text("Item"), bgcolor=COLOR_SURFACE, actions=actions_bar),
            ft.Tabs(selected_index=0, tabs=[
                ft.Tab(text="Dados", icon=ft.Icons.INFO, content=ft.ListView(expand=True, padding=20, spacing=15, controls=[ft.Text("Fotos (Max 5)", weight="bold"), ft.Container(content=images_row, height=110), txt_name, ft.Row([dd_sys, dd_cat]), ft.Row([dd_reg, dd_auth]), txt_storage, ft.Divider(), ft.Text("Detalhes", weight="bold"), ft.Row([chk_box, chk_manual]), txt_notes, ft.Container(height=20), ft.ElevatedButton("SALVAR DADOS", on_click=save_click, height=50, bgcolor=COLOR_PRIMARY, color="white"), ft.Container(height=50)])),
                ft.Tab(text="Valores", icon=ft.Icons.MONETIZATION_ON, content=ft.ListView(expand=True, padding=20, spacing=15, controls=[ft.Text("Financeiro", size=20, weight="bold"), txt_buy, txt_mkt, ft.Divider(), chk_sale, txt_sell, ft.Container(height=20), ft.ElevatedButton("SALVAR VALORES", on_click=save_click, height=50, bgcolor=COLOR_PRIMARY, color="white")])),
                ft.Tab(text="Testes / Manutenção", icon=ft.Icons.BUILD, content=ft.Container(padding=20, content=ft.Column([ft.Text("Histórico", size=18, weight="bold"), ft.Row([txt_log, ft.IconButton(ft.Icons.SEND, on_click=add_log)]), ft.Divider(), ft.Column([lv_logs], scroll=ft.ScrollMode.AUTO, expand=True)])))
            ], expand=True)
        ], bgcolor=COLOR_BG)

    # --- RELATÓRIO (REINSERIDO) ---
    def view_report():
        cnt, buy, mkt = db.get_stats()
        buy = buy or 0
        mkt = mkt or 0

        def gen_pdf(e):
            if not HAS_FPDF: show_snack("Erro biblioteca PDF", COLOR_ERROR); return
            try:
                items = db.get_items_for_sale_report()
                if not items: show_snack("Nada para vender", COLOR_WARNING); return
                
                temp_dir = tempfile.gettempdir()
                fname = f"Vendas_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                fpath = os.path.join(temp_dir, fname)

                pdf = PDF()
                pdf.add_page()
                pdf.set_font("Arial", size=16)
                pdf.cell(190, 10, txt="Catalogo de Venda", ln=1, align="C")
                pdf.ln(5)
                
                pdf.set_font("Arial", 'B', 8); pdf.set_fill_color(220, 220, 220)
                pdf.cell(65, 6, "Item", 1, 0, 'L', 1)
                pdf.cell(30, 6, "Sistema", 1, 0, 'C', 1)
                pdf.cell(30, 6, "Categ.", 1, 0, 'C', 1)
                pdf.cell(40, 6, "Obs", 1, 0, 'C', 1)
                pdf.cell(25, 6, "Valor", 1, 1, 'C', 1)
                
                pdf.set_font("Arial", size=8); total = 0
                for i in items:
                    val = i['selling_price'] or 0; total += val
                    nm = str(i['name']).encode('latin-1', 'replace').decode('latin-1')[:35]
                    pdf.cell(65, 6, nm, 1)
                    pdf.cell(30, 6, str(i['sys_name'])[:15], 1, 0, 'C')
                    pdf.cell(30, 6, str(i['cat_name'])[:15], 1, 0, 'C')
                    pdf.cell(40, 6, str(i['condition_notes'])[:22], 1)
                    pdf.cell(25, 6, f"{val:.2f}", 1, 1, 'R')
                
                pdf.set_font("Arial", 'B', 9)
                pdf.cell(165, 8, "TOTAL", 1, 0, 'R')
                pdf.cell(25, 8, f"{total:.2f}", 1, 1, 'R')
                
                pdf.output(fpath)
                try:
                    page.share_files_with_path([fpath])
                except:
                    show_snack(f"Salvo em: {fpath}", COLOR_WARNING)

            except Exception as x: show_snack(f"Erro PDF: {x}", COLOR_ERROR)

        def card(t, v, c):
            return ft.Container(content=ft.Column([ft.Text(t, size=12, color="grey"), ft.Text(v, size=18, weight="bold", color=c)], alignment="center", horizontal_alignment="center"), bgcolor=COLOR_SURFACE, padding=15, border_radius=10, expand=True)

        return ft.View(
            "/report",
            controls=[
                ft.AppBar(title=ft.Text("Relatório"), bgcolor=COLOR_SURFACE),
                ft.ListView(
                    expand=True, padding=20, spacing=20,
                    controls=[
                        ft.Container(content=ft.Column([ft.Text("Total Ativo", color="grey"), ft.Text(str(cnt), size=40, weight="bold")], horizontal_alignment="center"), alignment=ft.alignment.center, padding=20),
                        ft.Row([card("Investido", formatar_moeda(buy), COLOR_ERROR), card("Estimado", formatar_moeda(mkt), COLOR_SUCCESS)]),
                        ft.Divider(),
                        ft.ListTile(title=ft.Text("Gerar e Compartilhar PDF"), subtitle=ft.Text("Itens marcados 'À Venda'"), leading=ft.Icon(ft.Icons.SHARE, color=COLOR_PRIMARY), bgcolor=COLOR_SURFACE, shape=ft.RoundedRectangleBorder(radius=10), on_click=gen_pdf)
                    ]
                )
            ],
            bgcolor=COLOR_BG
        )

    def view_aux_manager():
        tbl = aux_context["table"]; ttl = aux_context["title"]
        lv = ft.ListView(expand=True, spacing=5, padding=10); txt_new = ft.TextField(label=f"Novo {ttl}"); txt_edit = ft.TextField(label="Nome"); edit_id = None
        def load():
            it = db.get_list_raw(tbl); lv.controls.clear()
            for i in it: lv.controls.append(ft.Container(content=ft.Row([ft.GestureDetector(content=ft.Text(i['name'], weight="bold", size=16), on_tap=lambda e, id=i['id'], val=i['name']: open_edit(id, val), expand=True), ft.IconButton(ft.Icons.DELETE, icon_color=COLOR_ERROR, on_click=lambda e, id=i['id']: dele(id))]), bgcolor=COLOR_SURFACE, padding=15, border_radius=5))
            page.update()
        def save_add(e):
            ok, m = db.add_aux(tbl,txt_new.value)
            if txt_new.value: show_snack(m,COLOR_SUCCESS if ok else COLOR_ERROR); 
            if ok: txt_new.value=""; page.close(dlg_add); load()
        def save_edit(e): 
            nonlocal edit_id; 
            ok, m = db.update_aux(tbl,edit_id,txt_edit.value)
            if txt_edit.value: show_snack(m,COLOR_SUCCESS if ok else COLOR_ERROR); 
            if ok: page.close(dlg_edit); load()
        def dele(uid): 
            if db.delete_aux(tbl, uid): show_snack("Apagado"); load()
        dlg_add = ft.AlertDialog(title=ft.Text(f"Novo {ttl}"), content=txt_new, actions=[ft.TextButton("Cancelar", on_click=lambda e: page.close(dlg_add)), ft.TextButton("Salvar", on_click=save_add)])
        dlg_edit = ft.AlertDialog(title=ft.Text("Editar"), content=txt_edit, actions=[ft.TextButton("Cancelar", on_click=lambda e: page.close(dlg_edit)), ft.TextButton("Salvar", on_click=save_edit)])
        def open_add(e): txt_new.value=""; page.open(dlg_add)
        def open_edit(uid, val): nonlocal edit_id; edit_id=uid; txt_edit.value=val; page.open(dlg_edit)
        load(); return ft.View("/aux", controls=[ft.AppBar(title=ft.Text(f"Gerir {ttl}"), bgcolor=COLOR_SURFACE), ft.Container(expand=True, content=lv, padding=10)], floating_action_button=ft.FloatingActionButton(icon=ft.Icons.ADD, bgcolor=COLOR_PRIMARY, on_click=open_add), bgcolor=COLOR_BG)

    def view_settings():
        def bk(e):
            try:
                zn = f"Backup_{datetime.now().strftime('%Y%m%d')}.zip"; 
                with zipfile.ZipFile(zn, 'w') as z:
                    if os.path.exists(DB_FILE): z.write(DB_FILE)
                    if os.path.exists(IMAGE_DIR): 
                        for r, d, f in os.walk(IMAGE_DIR): 
                            for fl in f: z.write(os.path.join(r, fl))
                show_snack(f"Criado: {zn}")
            except Exception as x: show_snack(f"Erro: {x}", COLOR_ERROR)
        def go_aux(t, l): aux_context["table"]=t; aux_context["title"]=l; page.go("/aux")
        return ft.View("/settings", controls=[ft.AppBar(title=ft.Text("Configurações"), bgcolor=COLOR_SURFACE), ft.ListView(expand=True, padding=10, controls=[ft.Text("Cadastros", weight="bold", color=COLOR_PRIMARY), ft.ListTile(title=ft.Text("Sistemas"), leading=ft.Icon(ft.Icons.GAMEPAD), on_click=lambda _: go_aux("Systems", "Sistemas")), ft.ListTile(title=ft.Text("Categorias"), leading=ft.Icon(ft.Icons.CATEGORY), on_click=lambda _: go_aux("Categories", "Categorias")), ft.ListTile(title=ft.Text("Regiões"), leading=ft.Icon(ft.Icons.MAP), on_click=lambda _: go_aux("Regions", "Regiões")), ft.ListTile(title=ft.Text("Autenticidade"), leading=ft.Icon(ft.Icons.VERIFIED), on_click=lambda _: go_aux("Authenticities", "Autenticidade")), ft.Divider(), ft.Text("Dados", weight="bold", color=COLOR_PRIMARY), ft.ListTile(title=ft.Text("Backup (Zip)"), leading=ft.Icon(ft.Icons.BACKUP), on_click=bk)])], bgcolor=COLOR_BG)

    def route_change(route):
        page.views.clear(); page.views.append(view_home())
        if page.route == "/categories": page.views.append(view_categories())
        elif page.route == "/items": page.views.append(view_item_list())
        elif page.route == "/form": page.views.append(view_form())
        elif page.route == "/report": page.views.append(view_report())
        elif page.route == "/settings": page.views.append(view_settings())
        elif page.route == "/aux": page.views.append(view_aux_manager())
        page.update()
    def view_pop(view): page.views.pop(); top = page.views[-1]; page.go(top.route)
    def go_to_categories(sid, sn): nav_context["sys_id"]=sid; nav_context["sys_name"]=sn; page.go("/categories")
    def go_to_items(cid, cn): nav_context["cat_id"]=cid; nav_context["cat_name"]=cn; page.go("/items")
    def go_to_add(): nonlocal editing_id, picked_image_path; editing_id=None; picked_image_path=None; page.go("/form")
    def go_to_edit(uid): nonlocal editing_id, picked_image_path; editing_id=uid; picked_image_path=None; page.go("/form")
    page.on_route_change = route_change; page.on_view_pop = view_pop; page.go(page.route)

if __name__ == "__main__":
    ft.app(target=main, assets_dir="assets")