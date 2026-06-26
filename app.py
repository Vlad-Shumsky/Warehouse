import streamlit as st # type: ignore
import pandas as pd # type: ignore
from sqlalchemy import text # type: ignore
import hashlib

st.set_page_config(page_title="Управление складом", page_icon="📦", layout="centered")

TABLE_NAME = "warehouse_inventory"  
USER_TABLE = "warehouse_users"
conn = st.connection("postgresql", type="sql")

# Вспомогательная функция для очистки текста до чистых букв и цифр
def clean_alphanumeric(text_input):
    return "".join(c for c in text_input if c.isalnum())

# Безопасность: Хеширование паролей через SHA-256
def make_hash(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

# Инициализация состояния авторизации
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = ""

# =========================================================
# ОКНО ВХОДА И РЕГИСТРАЦИИ
# =========================================================
if not st.session_state.authenticated:
    st.title("🔐 Контроль доступа")
    
    auth_tab1, auth_tab2 = st.tabs(["🔑 Вход", "📝 Регистрация"])
    
    with auth_tab1:
        st.subheader("Авторизация")
        login_user = st.text_input("Логин (Имя пользователя):", key="login_user_input").strip().lower()
        login_pass = st.text_input("Пароль:", type="password", key="login_pass_input")
        
        if st.button("Войти", use_container_width=True):
            if login_user and login_pass:
                # Ищем хеш пароля пользователя в базе данных
                user_query = f"SELECT password_hash FROM {USER_TABLE} WHERE username = :user;"
                res = conn.query(user_query, params={"user": login_user}, ttl=0)
                
                if not res.empty:
                    saved_hash = res.iloc[0]["password_hash"]
                    if make_hash(login_pass) == saved_hash:
                        st.session_state.authenticated = True
                        st.session_state.username = login_user
                        st.rerun()
                    else:
                        st.error("❌ Неверный пароль.")
                else:
                    st.error("❌ Пользователь с таким логином не найден.")
            else:
                st.warning("Пожалуйста, заполните оба поля.")
                
    with auth_tab2:
        st.subheader("Регистрация нового сотрудника")
        reg_user = st.text_input("Придумайте логин:", key="reg_user_input").strip().lower()
        reg_pass = st.text_input("Придумайте пароль:", type="password", key="reg_pass_input")
        reg_pass_conf = st.text_input("Подтвердите пароль:", type="password", key="reg_pass_conf_input")
        
        # 🔐 NEW: The gatekeeper field
        reg_key = st.text_input("Ключ регистрации (Выдается администратором):", type="password", key="reg_key_input")
        
        if st.button("Создать аккаунт", use_container_width=True):
            if reg_user and reg_pass and reg_key:
                # Pull the master secret key from your hidden configuration
                master_key = st.secrets.get("registration", {}).get("master_key", "FALLBACK_NOT_SET")
                
                if reg_key != master_key:
                    st.error("❌ Неверный ключ регистрации. Доступ отклонен.")
                elif reg_pass != reg_pass_conf:
                    st.error("❌ Пароли не совпадают.")
                elif len(reg_pass) < 4:
                    st.error("❌ Пароль должен содержать не менее 4 символов.")
                else:
                    # Check if username is already taken
                    check_query = f"SELECT username FROM {USER_TABLE} WHERE username = :user;"
                    dup_user = conn.query(check_query, params={"user": reg_user}, ttl=0)
                    
                    if not dup_user.empty:
                        st.error("❌ Этот логин уже занят.")
                    else:
                        # Write the new user details with a hashed password
                        hashed = make_hash(reg_pass)
                        with conn.session as session:
                            session.execute(
                                text(f"INSERT INTO {USER_TABLE} (username, password_hash) VALUES (:user, :pass_hash);"),
                                {"user": reg_user, "pass_hash": hashed}
                            )
                            session.commit()
                        st.success("🎉 Аккаунт успешно создан! Теперь вы можете войти на вкладке 'Вход'.")
            else:
                st.warning("Все поля обязательны для заполнения.")

# =========================================================
# ОСНОВНОЙ ИНТЕРФЕЙС ПРИЛОЖЕНИЯ (ПОСЛЕ ВХОДА)
# =========================================================
else:
    # Боковая панель (Sidebar) с информацией о сессии и кнопкой выхода
    st.sidebar.title("👤 Пользователь")
    st.sidebar.write(f"Вы вошли как: **{st.session_state.username.upper()}**")
    if st.sidebar.button("🚪 Выйти из системы", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.username = ""
        st.rerun()

    st.title("📦 Управление складом")

    tab1, tab2 = st.tabs(["⚡ Найти/добавить", "📊 Список"])

    # =========================================================
    # ВКЛАДКА 1: ОПЕРАЦИИ (ПОИСК, ИЗЪЯТИЕ, ДОБАВЛЕНИЕ)
    # =========================================================
    with tab1:
        st.header("🔍 Найти/изъять товар")
        lookup_sku = st.text_input("Введите артикул:", key="lookup_field").strip()

        if lookup_sku:
            cleaned_search = clean_alphanumeric(lookup_sku).lower()
            
            query = f"""
                SELECT sku, location, quantity, last_replenished 
                FROM {TABLE_NAME} 
                WHERE LOWER(REPLACE(REPLACE(sku, '*', ''), ' ', '')) LIKE :sku_param;
            """
            df_results = conn.query(query, params={"sku_param": f"%{cleaned_search}%"}, ttl=0)
            
            if not df_results.empty:
                st.write("Результаты поиска:")
                
                options = {}
                for idx, row in df_results.iterrows():
                    date_str = row['last_replenished'].strftime("%d.%m.%Y") if row['last_replenished'] else "Unknown"
                    label = f"📦 Артикул: :orange[{row['sku']}] | Место: :blue[{row['location']}] | Количество: {row['quantity']} (Пополнено: {date_str})"
                    
                    options[f"{row['sku']}|||{row['location']}"] = {
                        "label": label, 
                        "sku": row['sku'],
                        "location": row['location'], 
                        "current_qty": int(row['quantity'])
                    }
                
                selected_key = st.radio("Выберите из какого места вы берёте товар:", options=list(options.keys()), format_func=lambda x: options[x]["label"])
                chosen = options[selected_key]
                
                take_qty = st.number_input("Количество:", min_value=1, max_value=chosen["current_qty"], value=1, step=1)
                
                if st.button("Подтвердить изъятие товара"):
                    if take_qty > chosen["current_qty"]:
                        st.error(f"❌ Недостаточно товара. Есть только {chosen['current_qty']} штук.")
                    else:
                        with conn.session as session:
                            if take_qty == chosen["current_qty"]:
                                session.execute(
                                    text(f"DELETE FROM {TABLE_NAME} WHERE sku = :sku AND location = :loc;"), 
                                    {"sku": chosen["sku"], "loc": chosen["location"]}
                                )
                                st.toast(f"✅ {chosen['sku']} изъято из {chosen['location']}.")
                            else:
                                new_qty = chosen["current_qty"] - take_qty
                                session.execute(
                                    text(f"UPDATE {TABLE_NAME} SET quantity = :new_qty WHERE sku = :sku AND location = :loc;"),
                                    {"new_qty": new_qty, "sku": chosen["sku"], "loc": chosen["location"]}
                                )
                                st.toast(f"✅ Изъято {take_qty} штук.")
                            session.commit()
                        st.rerun()
            else:
                st.error("❌ Артикул отсутствует в базе.")

        st.markdown("---")

        st.header("➕ Добавить товар")
        
        MAPPING_TABLE = "barcode_mapping"

        # 1. Initialize all memory states at the top
        if "clear_add_fields" not in st.session_state:
            st.session_state["clear_add_fields"] = False
        if "add_success_msg" not in st.session_state:
            st.session_state["add_success_msg"] = None
        if "last_processed_input" not in st.session_state:
            st.session_state.last_processed_input = ""
        if "was_autofilled" not in st.session_state:
            st.session_state["was_autofilled"] = False

        # Pre-emptive field clearance BEFORE widgets are drawn
        if st.session_state["clear_add_fields"]:
            st.session_state["add_sku_field"] = ""
            st.session_state["add_loc_field"] = ""
            st.session_state["last_processed_input"] = ""
            st.session_state["was_autofilled"] = False
            st.session_state["clear_add_fields"] = False

        # 2. Intercept, clean, and format input BEFORE rendering the text box
        if "add_sku_field" in st.session_state and st.session_state["add_sku_field"].strip():
            current_input = st.session_state["add_sku_field"].strip()
            clean_input = clean_alphanumeric(current_input).upper()
            
            if st.session_state.last_processed_input != clean_input:
                st.session_state["was_autofilled"] = False
                
                # Check cross-reference table for a barcode match
                map_query = f"SELECT sku FROM {MAPPING_TABLE} WHERE barcode = :barcode LIMIT 1;"
                map_df = conn.query(map_query, params={"barcode": clean_input}, ttl=0)
                
                if not map_df.empty:
                    # Found a barcode! Strip whatever format Excel has down to 8 raw characters
                    raw_sku = clean_alphanumeric(str(map_df.iloc[0]["sku"])).upper()
                else:
                    # No barcode found; treat the input itself as a raw manual SKU entry
                    raw_sku = clean_input

                # Apply pretty formatting uniform structure if it resolves to an 8-char SKU
                if len(raw_sku) == 8:
                    pretty_sku = f"{raw_sku[:3]}*{raw_sku[3:5]} {raw_sku[5:]}"
                    # 🔄 FORCE VISUAL SWAP: Overwrite the box value with the beautiful format
                    st.session_state["add_sku_field"] = pretty_sku
                    target_sku_for_lookup = pretty_sku
                else:
                    target_sku_for_lookup = raw_sku

                # Look up existing warehouse location using the standardized SKU format
                if len(raw_sku) == 8:
                    loc_query = f"SELECT location FROM {TABLE_NAME} WHERE sku = :sku LIMIT 1;"
                    loc_df = conn.query(loc_query, params={"sku": target_sku_for_lookup}, ttl=0)
                    
                    if not loc_df.empty:
                        st.session_state["add_loc_field"] = str(loc_df.iloc[0]["location"])
                        st.session_state["was_autofilled"] = True
                    else:
                        st.session_state["add_loc_field"] = ""
                else:
                    st.session_state["add_loc_field"] = ""
                
                # Lock down this cleaned token to prevent redundant query loops
                st.session_state.last_processed_input = clean_input
        else:
            st.session_state.last_processed_input = ""
            st.session_state["was_autofilled"] = False

        # 3. Render the main SKU/Barcode input field
        raw_input = st.text_input("Штрихкод или Артикул:", key="add_sku_field").strip()

        # Dismiss old success message on fresh interaction
        if raw_input and st.session_state["add_success_msg"]:
            st.session_state["add_success_msg"] = None

        # 4. Precision Blue Info Box (Only triggers on a genuine database autofill)
        if st.session_state["was_autofilled"] and not st.session_state["add_success_msg"]:
            st.info(f"💡 Этот артикул уже есть на складе в ячейке: **{st.session_state['add_loc_field']}**. Место подставлено автоматически.")

        # 5. Render remaining input elements
        new_location = st.text_input("Место на складе:", key="add_loc_field").strip()
        add_qty = st.number_input("Количество:", min_value=1, value=1, step=1, key="add_qty_field")
        
        if st.session_state["add_success_msg"]:
            st.success(st.session_state["add_success_msg"])

        # 6. Submission Execution block
        submit_btn = st.button("Добавить товар в базу", use_container_width=True)
        
        if submit_btn:
            if raw_input and new_location:
                clean_input = clean_alphanumeric(raw_input).upper()
                
                # Re-resolve backend mapping safely on submit action
                map_query = f"SELECT sku FROM {MAPPING_TABLE} WHERE barcode = :barcode LIMIT 1;"
                map_df = conn.query(map_query, params={"barcode": clean_input}, ttl=0)
                final_sku_raw = clean_alphanumeric(str(map_df.iloc[0]["sku"])).upper() if not map_df.empty else clean_input
                
                if len(final_sku_raw) != 8:
                    st.error(f"❌ Не удалось распознать артикул (Длина: {len(final_sku_raw)}). Проверьте таблицу соответствий.")
                else:
                    formatted_sku = f"{final_sku_raw[:3]}*{final_sku_raw[3:5]} {final_sku_raw[5:]}"
                    
                    check_query = f"SELECT quantity FROM {TABLE_NAME} WHERE sku = :sku AND location = :loc;"
                    dup_check = conn.query(check_query, params={"sku": formatted_sku, "loc": new_location}, ttl=0)
                    
                    with conn.session as session:
                        if not dup_check.empty:
                            existing_qty = int(dup_check.iloc[0]["quantity"])
                            new_total = existing_qty + add_qty
                            session.execute(
                                text(f"UPDATE {TABLE_NAME} SET quantity = :qty, last_replenished = NOW() WHERE sku = :sku AND location = :loc;"),
                                {"qty": new_total, "sku": formatted_sku, "loc": new_location}
                            )
                            st.session_state["add_success_msg"] = f"✅ Артикул **{formatted_sku}** в **{new_location}** пополнен. Всего: {new_total} штук."
                        else:
                            session.execute(
                                text(f"INSERT INTO {TABLE_NAME} (sku, location, quantity) VALUES (:sku, :loc, :qty);"),
                                {"sku": formatted_sku, "loc": new_location, "qty": add_qty}
                            )
                            st.session_state["add_success_msg"] = f"✅ Артикул **{formatted_sku}** добавлен в **{new_location}**."
                        session.commit()
                    
                    st.session_state["clear_add_fields"] = True
                    st.rerun()
            else:
                st.warning("Пожалуйста, заполните все поля.")

    # =========================================================
    # ВКЛАДКА 2: ПРОСМОТР БАЗЫ (СПИСОК)
    # =========================================================
    with tab2:
        st.header("📋 Список товаров на складе")
        
        search_col1, search_col2 = st.columns(2)
        with search_col1:
            browser_sku = st.text_input("Поиск по артикулу:", value="", key="browser_sku_input").strip()
        with search_col2:
            search_loc = st.text_input("Поиск по месту:", value="", key="browser_loc").strip()
        
        base_query = f"SELECT sku, location, quantity, last_replenished FROM {TABLE_NAME} WHERE 1=1"
        params = {}
        
        if browser_sku:
            cleaned_browser_sku = clean_alphanumeric(browser_sku).lower()
            base_query += " AND LOWER(REPLACE(REPLACE(sku, '*', ''), ' ', '')) LIKE :sku_param"
            params["sku_param"] = f"%{cleaned_browser_sku}%"
        if search_loc:
            base_query += " AND location ILIKE :loc"
            params["loc"] = f"%{search_loc}%"
            
        base_query += " ORDER BY location ASC, sku ASC;"
        
        df_all = conn.query(base_query, params=params, ttl=0)
        
        if not df_all.empty:
            df_display = df_all.copy()
            df_display.columns = ["Артикул", "Место на складе", "Количество", "Последнее пополнение"]
            if df_display["Последнее пополнение"].dt.tz is not None:
                df_display["Последнее пополнение"] = df_display["Последнее пополнение"].dt.tz_localize(None)
                
            st.dataframe(df_display, use_container_width=True, hide_index=True)
            st.caption(f"Найдено позиций: {len(df_display)}.")
        else:
            st.info("Товары не найдены.")
