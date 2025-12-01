import flet as ft
import sqlite3
import uuid
import os
import shutil
import zipfile
from datetime import datetime

# --- CONSTANTES ---
DB_FILE = "retro_collection_v3.db"
IMAGE_DIR = "retro_images"

# Cores do tema Gnome / Adwaita Dark
COLOR_BG = "#1E1E1E"        # Fundo Cinza Carvão
COLOR_SURFACE = "#303030"   # Fundo de cartões/listas
COLOR_PRIMARY = "#3584e4"   # Azul Gnome Vibrante
COLOR_TEXT = "#ffffff"

# ===================================================================
# ===== BANCO DE DADOS ==============================================
# ===================================================================
class DatabaseManager:
    def __init__(self):
        self.conn = None
        self.create_tables()

    def connect(self):
        self.conn = sqlite3.connect(DB_FILE)
        self.conn.row_factory = sqlite3.Row
        return self.conn.cursor()

    def close(self):
        if self.conn: self.conn.close()

    def create_tables(self):
        c = self.connect()
        # Tabelas Auxiliares
        for table in ["Systems", "Categories", "Regions", "Authenticities"]:
            c.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, name TEXT UNIQUE)")
        
        # Tabela Principal
        c.execute("""CREATE TABLE IF NOT EXISTS Items (
            id TEXT PRIMARY KEY, name TEXT, category_id TEXT, system_id TEXT, authenticity_id TEXT, region_id TEXT,
            has_box INTEGER, has_manual INTEGER, condition_notes TEXT, storage_location TEXT,
            purchase_price REAL, market_value REAL, selling_price REAL, is_for_sale INTEGER,
            image_filename TEXT, last_modified TIMESTAMP, is_deleted INTEGER DEFAULT 0
        )""")
        self.conn.commit()
        self.close()

    def get_list(self, table):
        c = self.connect()
        try:
            c.execute(f"SELECT id, name FROM {table} ORDER BY name")
            res = c.fetchall()
        except:
            res = []
        self.close()
        # Retorna lista formatada para o Dropdown do Flet
        return [ft.dropdown.Option(key=row['id'], text=row['name']) for row in res]

    def add_aux(self, table, name):
        try:
            uid = str(uuid.uuid4())
            c = self.connect()
            c.execute(f"INSERT INTO {table} (id, name) VALUES (?,?)", (uid, name))
            self.conn.commit()
            self.close()
            return True
        except: 
            return False

    def delete_item(self, uid):
        c = self.connect()
        c.execute("UPDATE Items SET is_deleted = 1 WHERE id = ?", (uid,))
        self.conn.commit()
        self.close()

    def get_item(self, uid):
        c = self.connect()
        c.execute("SELECT * FROM Items WHERE id=?", (uid,))
        row = c.fetchone()
        self.close()
        return row

    def save_item(self, data, uid=None):
        c = self.connect()
        if not uid:
            uid = str(uuid.uuid4())
            c.execute("""INSERT INTO Items (id, name, system_id, category_id, region_id, authenticity_id, 
                         storage_location, purchase_price, market_value, selling_price, is_for_sale, 
                         condition_notes, has_box, has_manual, image_filename) 
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (uid, data['name'], data['system_id'], data['category_id'], data['region_id'], 
                       data['authenticity_id'], data['storage_location'], data['purchase_price'], 
                       data['market_value'], data['selling_price'], data['is_for_sale'], 
                       data['condition_notes'], data['has_box'], data['has_manual'], data['image_filename']))
        else:
            c.execute("""UPDATE Items SET name=?, system_id=?, category_id=?, region_id=?, authenticity_id=?, 
                         storage_location=?, purchase_price=?, market_value=?, selling_price=?, is_for_sale=?, 
                         condition_notes=?, has_box=?, has_manual=?, image_filename=? WHERE id=?""",
                      (data['name'], data['system_id'], data['category_id'], data['region_id'], 
                       data['authenticity_id'], data['storage_location'], data['purchase_price'], 
                       data['market_value'], data['selling_price'], data['is_for_sale'], 
                       data['condition_notes'], data['has_box'], data['has_manual'], data['image_filename'], uid))
        self.conn.commit()
        self.close()

    def get_stats(self):
        c = self.connect()
        c.execute("SELECT COUNT(*), SUM(purchase_price), SUM(market_value) FROM Items WHERE is_deleted=0")
        res = c.fetchone()
        self.close()
        return res

db = DatabaseManager()

# ===================================================================
# ===== APP PRINCIPAL (FLET) ========================================
# ===================================================================

def main(page: ft.Page):
    page.title = "Retro-Estante Mobile"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = COLOR_BG
    
    # Configuração do Tema Visual
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=COLOR_PRIMARY,
            background=COLOR_BG,
            surface=COLOR_SURFACE,
        )
    )

    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)

    # --- Estados Globais ---
    editing_id = None
    picked_image_path = None
    
    # Refs para atualizar a UI
    image_preview_ref = ft.Ref[ft.Image]()
    btn_image_text_ref = ft.Ref[ft.ElevatedButton]()

    # --- File Picker (Câmera/Galeria) ---
    def on_file_picked(e: ft.FilePickerResultEvent):
        nonlocal picked_image_path
        if e.files and len(e.files) > 0:
            picked_image_path = e.files[0].path
            # Atualiza visualização na tela
            if image_preview_ref.current:
                image_preview_ref.current.src = picked_image_path
                image_preview_ref.current.update()
            if btn_image_text_ref.current:
                btn_image_text_ref.current.text = "Imagem Selecionada!"
                btn_image_text_ref.current.update()

    file_picker = ft.FilePicker(on_result=on_file_picked)
    page.overlay.append(file_picker)

    # --- Helpers ---
    def formatar_moeda(val):
        try: return f"R$ {float(val):,.2f}"
        except: return "R$ 0.00"

    # ===============================================================
    # ===== TELAS (VIEWS) ===========================================
    # ===============================================================

    def view_home():
        # Busca itens no banco
        c = db.connect()
        try:
            c.execute("""SELECT i.id, i.name, s.name as sys_name, i.image_filename, i.is_for_sale 
                        FROM Items i LEFT JOIN Systems s ON i.system_id = s.id 
                        WHERE i.is_deleted=0 ORDER BY i.name""")
            items_db = c.fetchall()
        except:
            items_db = []
        db.close()

        list_items = []
        for row in items_db:
            subtitle_text = row['sys_name'] if row['sys_name'] else "Sem Sistema"
            icon_used = ft.Icons.GAMEPAD  # CORRIGIDO
            icon_col = ft.colors.WHITE
            
            if row['is_for_sale']:
                subtitle_text += " • À VENDA"
                icon_used = ft.Icons.ATTACH_MONEY # CORRIGIDO
                icon_col = ft.colors.GREEN_400

            list_items.append(
                ft.ListTile(
                    leading=ft.Icon(icon_used, color=icon_col),
                    title=ft.Text(row['name'], weight=ft.FontWeight.BOLD),
                    subtitle=ft.Text(subtitle_text),
                    bgcolor=COLOR_SURFACE,
                    on_click=lambda e, uid=row['id']: go_to_edit(uid),
                    shape=ft.RoundedRectangleBorder(radius=10),
                )
            )

        return ft.View(
            "/",
            controls=[
                ft.AppBar(
                    title=ft.Text("Retro-Estante"), 
                    bgcolor=COLOR_SURFACE, 
                    actions=[
                        ft.IconButton(ft.Icons.BAR_CHART, on_click=lambda _: page.go("/report")), # CORRIGIDO
                        ft.IconButton(ft.Icons.SETTINGS, on_click=lambda _: page.go("/settings")), # CORRIGIDO
                    ]
                ),
                ft.ListView(
                    controls=list_items, 
                    expand=True, 
                    spacing=10, 
                    padding=10
                ),
                ft.FloatingActionButton(
                    icon=ft.Icons.ADD, # CORRIGIDO
                    bgcolor=COLOR_PRIMARY, 
                    on_click=lambda _: go_to_add()
                )
            ],
            bgcolor=COLOR_BG
        )

    def view_form():
        nonlocal editing_id, picked_image_path
        
        # Criação dos controles
        txt_name = ft.TextField(label="Nome do Jogo", border_radius=10)
        
        # Dropdowns carregando do banco
        dd_sys = ft.Dropdown(label="Sistema", options=db.get_list("Systems"), border_radius=10, expand=True)
        dd_cat = ft.Dropdown(label="Categoria", options=db.get_list("Categories"), border_radius=10, expand=True)
        dd_reg = ft.Dropdown(label="Região", options=db.get_list("Regions"), border_radius=10, expand=True)
        dd_auth = ft.Dropdown(label="Autenticidade", options=db.get_list("Authenticities"), border_radius=10, expand=True)
        
        txt_storage = ft.TextField(label="Localização Física", icon=ft.Icons.INVENTORY_2, border_radius=10) # CORRIGIDO
        
        chk_box = ft.Switch(label="Possui Caixa?")
        chk_manual = ft.Switch(label="Possui Manual?")
        
        txt_price_buy = ft.TextField(label="Pago (R$)", keyboard_type=ft.KeyboardType.NUMBER, expand=True, border_radius=10)
        txt_price_mkt = ft.TextField(label="Mercado (R$)", keyboard_type=ft.KeyboardType.NUMBER, expand=True, border_radius=10)
        
        chk_sale = ft.Switch(label="Colocar à Venda?")
        txt_price_sell = ft.TextField(label="Preço Venda (R$)", keyboard_type=ft.KeyboardType.NUMBER, border_radius=10, disabled=True)
        
        def on_sale_change(e):
            txt_price_sell.disabled = not chk_sale.value
            txt_price_sell.update()
        chk_sale.on_change = on_sale_change

        txt_notes = ft.TextField(label="Notas / Estado", multiline=True, min_lines=3, border_radius=10)

        img_preview = ft.Image(src="", height=200, fit=ft.ImageFit.CONTAIN, ref=image_preview_ref)
        
        # Preencher dados se for edição
        current_img_db = None
        if editing_id:
            row = db.get_item(editing_id)
            if row:
                txt_name.value = row['name']
                dd_sys.value = row['system_id']
                dd_cat.value = row['category_id']
                dd_reg.value = row['region_id']
                dd_auth.value = row['authenticity_id']
                txt_storage.value = row['storage_location']
                txt_price_buy.value = str(row['purchase_price'] or 0)
                txt_price_mkt.value = str(row['market_value'] or 0)
                txt_price_sell.value = str(row['selling_price'] or 0)
                chk_box.value = bool(row['has_box'])
                chk_manual.value = bool(row['has_manual'])
                chk_sale.value = bool(row['is_for_sale'])
                txt_price_sell.disabled = not chk_sale.value
                txt_notes.value = row['condition_notes']
                
                if row['image_filename']:
                    full_path = os.path.join(IMAGE_DIR, row['image_filename'])
                    if os.path.exists(full_path):
                        img_preview.src = full_path
                        current_img_db = row['image_filename']

        def save_click(e):
            final_img_name = current_img_db
            
            # Se selecionou nova imagem
            if picked_image_path:
                try:
                    ext = os.path.splitext(picked_image_path)[1]
                    if not ext: ext = ".jpg"
                    new_filename = f"{uuid.uuid4()}{ext}"
                    shutil.copy(picked_image_path, os.path.join(IMAGE_DIR, new_filename))
                    final_img_name = new_filename
                except Exception as ex:
                    print(f"Erro ao salvar imagem: {ex}")

            data = {
                'name': txt_name.value,
                'system_id': dd_sys.value,
                'category_id': dd_cat.value,
                'region_id': dd_reg.value,
                'authenticity_id': dd_auth.value,
                'storage_location': txt_storage.value,
                'purchase_price': float(txt_price_buy.value or 0),
                'market_value': float(txt_price_mkt.value or 0),
                'selling_price': float(txt_price_sell.value or 0),
                'is_for_sale': 1 if chk_sale.value else 0,
                'condition_notes': txt_notes.value,
                'has_box': 1 if chk_box.value else 0,
                'has_manual': 1 if chk_manual.value else 0,
                'image_filename': final_img_name
            }
            
            if not data['name']:
                page.snack_bar = ft.SnackBar(ft.Text("Nome é obrigatório!"))
                page.snack_bar.open = True
                page.update()
                return

            db.save_item(data, editing_id)
            page.go("/")

        def delete_click(e):
            if editing_id:
                db.delete_item(editing_id)
                page.go("/")

        # Estrutura visual da tela de Formulário
        return ft.View(
            "/form",
            controls=[
                ft.AppBar(
                    title=ft.Text("Editar Item" if editing_id else "Novo Item"), 
                    bgcolor=COLOR_SURFACE,
                    actions=[
                        ft.IconButton(ft.Icons.DELETE, on_click=delete_click) if editing_id else ft.Container() # CORRIGIDO
                    ]
                ),
                ft.ListView(
                    expand=True,
                    padding=20,
                    spacing=15,
                    controls=[
                        ft.Container(
                            content=img_preview,
                            alignment=ft.alignment.center,
                            bgcolor="#000000",
                            border_radius=10
                        ),
                        ft.ElevatedButton(
                            "Selecionar Foto", 
                            icon=ft.Icons.CAMERA_ALT,  # CORRIGIDO
                            on_click=lambda _: file_picker.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE),
                            ref=btn_image_text_ref
                        ),
                        txt_name,
                        ft.Row([dd_sys, dd_cat]),
                        ft.Row([dd_reg, dd_auth]),
                        txt_storage,
                        ft.Divider(),
                        ft.Text("Detalhes", size=16, weight="bold"),
                        ft.Row([chk_box, chk_manual]),
                        txt_notes,
                        ft.Divider(),
                        ft.Text("Financeiro", size=16, weight="bold"),
                        ft.Row([txt_price_buy, txt_price_mkt]),
                        chk_sale,
                        txt_price_sell,
                        ft.Container(height=20),
                        ft.ElevatedButton(
                            "SALVAR ITEM", 
                            on_click=save_click, 
                            height=50, 
                            bgcolor=COLOR_PRIMARY, 
                            color="white"
                        ),
                    ]
                )
            ],
            bgcolor=COLOR_BG
        )

    def view_report():
        count, buy, mkt = db.get_stats()
        buy = buy or 0
        mkt = mkt or 0
        profit = mkt - buy
        
        def card_stat(title, value, color_val):
            return ft.Container(
                content=ft.Column([
                    ft.Text(title, size=12, color="grey"),
                    ft.Text(value, size=18, weight="bold", color=color_val)
                ], alignment="center", horizontal_alignment="center"),
                bgcolor=COLOR_SURFACE,
                padding=15,
                border_radius=10,
                expand=True
            )

        return ft.View(
            "/report",
            controls=[
                ft.AppBar(title=ft.Text("Relatório"), bgcolor=COLOR_SURFACE),
                ft.Column(
                    controls=[
                        ft.Container(
                            content=ft.Column([
                                ft.Text("Total de Itens", color="grey"),
                                ft.Text(str(count), size=40, weight="bold")
                            ], horizontal_alignment="center"),
                            alignment=ft.alignment.center,
                            padding=20
                        ),
                        ft.Row([
                            card_stat("Investido", formatar_moeda(buy), ft.colors.RED_400),
                            card_stat("Valor Mercado", formatar_moeda(mkt), ft.colors.GREEN_400)
                        ]),
                        ft.Container(height=20),
                        ft.Container(
                            content=ft.Text(f"Lucro Estimado: {formatar_moeda(profit)}", size=20, color=COLOR_PRIMARY),
                            alignment=ft.alignment.center
                        ),
                    ],
                    padding=20
                )
            ],
            bgcolor=COLOR_BG
        )

    def view_settings():
        dlg_input = ft.TextField(label="Nome")
        target_table = ""

        def add_item_aux(e):
            if dlg_input.value:
                db.add_aux(target_table, dlg_input.value)
                dlg_input.value = ""
                page.dialog.open = False
                page.update()
                page.snack_bar = ft.SnackBar(ft.Text("Adicionado com sucesso!"))
                page.snack_bar.open = True
                page.update()

        def open_dlg(table, title):
            nonlocal target_table
            target_table = table
            page.dialog = ft.AlertDialog(
                title=ft.Text(title),
                content=dlg_input,
                actions=[ft.TextButton("Salvar", on_click=add_item_aux)]
            )
            page.dialog.open = True
            page.update()

        def backup_click(e):
            try:
                zip_name = f"Backup_{datetime.now().strftime('%Y%m%d')}.zip"
                with zipfile.ZipFile(zip_name, 'w') as z:
                    if os.path.exists(DB_FILE): z.write(DB_FILE)
                    if os.path.exists(IMAGE_DIR):
                        for root, dirs, files in os.walk(IMAGE_DIR):
                            for file in files: z.write(os.path.join(root, file))
                page.snack_bar = ft.SnackBar(ft.Text(f"Backup criado: {zip_name}"))
            except Exception as ex:
                page.snack_bar = ft.SnackBar(ft.Text(f"Erro: {ex}"))
            page.snack_bar.open = True
            page.update()

        return ft.View(
            "/settings",
            controls=[
                ft.AppBar(title=ft.Text("Configurações"), bgcolor=COLOR_SURFACE),
                ft.ListView(
                    controls=[
                        ft.ListTile(title=ft.Text("Adicionar Sistema"), leading=ft.Icon(ft.Icons.ADD), on_click=lambda _: open_dlg("Systems", "Novo Sistema")), # CORRIGIDO
                        ft.ListTile(title=ft.Text("Adicionar Categoria"), leading=ft.Icon(ft.Icons.CATEGORY), on_click=lambda _: open_dlg("Categories", "Nova Categoria")), # CORRIGIDO
                        ft.ListTile(title=ft.Text("Adicionar Região"), leading=ft.Icon(ft.Icons.MAP), on_click=lambda _: open_dlg("Regions", "Nova Região")), # CORRIGIDO
                        ft.ListTile(title=ft.Text("Adicionar Autenticidade"), leading=ft.Icon(ft.Icons.VERIFIED), on_click=lambda _: open_dlg("Authenticities", "Nova Autenticidade")), # CORRIGIDO
                        ft.Divider(),
                        ft.ListTile(title=ft.Text("Fazer Backup (Zip)"), leading=ft.Icon(ft.Icons.BACKUP, color=COLOR_PRIMARY), on_click=backup_click), # CORRIGIDO
                    ]
                )
            ],
            bgcolor=COLOR_BG
        )

    # --- Roteamento ---
    def route_change(route):
        page.views.clear()
        page.views.append(view_home())
        
        if page.route == "/form":
            page.views.append(view_form())
        elif page.route == "/report":
            page.views.append(view_report())
        elif page.route == "/settings":
            page.views.append(view_settings())
            
        page.update()

    def view_pop(view):
        page.views.pop()
        top_view = page.views[-1]
        page.go(top_view.route)

    def go_to_add():
        nonlocal editing_id, picked_image_path
        editing_id = None
        picked_image_path = None
        page.go("/form")

    def go_to_edit(uid):
        nonlocal editing_id, picked_image_path
        editing_id = uid
        picked_image_path = None
        page.go("/form")

    page.on_route_change = route_change
    page.on_view_pop = view_pop
    page.go(page.route)

# Inicialização
if __name__ == "__main__":
    ft.app(target=main)