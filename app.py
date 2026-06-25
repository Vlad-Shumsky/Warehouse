import streamlit as st
import pandas as pd
from sqlalchemy import text

st.set_page_config(page_title="Warehouse Station", page_icon="📦", layout="centered")
st.title("📦 Smart-Format Warehouse System")

TABLE_NAME = "warehouse_inventory"  
conn = st.connection("postgresql", type="sql")

# Helper function to clean text down to pure alphanumeric characters
def clean_alphanumeric(text_input):
    return "".join(c for c in text_input if c.isalnum())

# Split the app into two clean views
tab1, tab2 = st.tabs(["⚡ Station Operations", "📊 Inventory Browser"])

# =========================================================
# TAB 1: DAILY OPERATIONS (LOOKUP, TAKE, ADD)
# =========================================================
with tab1:
    st.header("🔍 Find & Take Items")
    lookup_sku = st.text_input("Scan or Type SKU (Any format, case-insensitive):", key="lookup_field").strip()

    if lookup_sku:
        # Clean user search input to pure lowercase alphanumeric
        cleaned_search = clean_alphanumeric(lookup_sku).lower()
        
        # SQL trick: Strip '*' and ' ' out of the DB column on the fly for comparison
        query = f"""
            SELECT sku, location, quantity, last_replenished 
            FROM {TABLE_NAME} 
            WHERE LOWER(REPLACE(REPLACE(sku, '*', ''), ' ', '')) LIKE :sku_param;
        """
        df_results = conn.query(query, params={"sku_param": f"%{cleaned_search}%"}, ttl=0)
        
        if not df_results.empty:
            st.write("### 📍 Matches Found:")
            
            # Map out options. We display the exact SKU format from DB so worker is confident.
            options = {}
            for idx, row in df_results.iterrows():
                date_str = row['last_replenished'].strftime("%Y-%m-%d") if row['last_replenished'] else "Unknown"
                label = f"📦 SKU: {row['sku']} | Bin: {row['location']} | Stock: {row['quantity']} (Refreshed: {date_str})"
                # Key using a unique string combo of SKU + Location
                options[f"{row['sku']}|||{row['location']}"] = {
                    "label": label, 
                    "sku": row['sku'],
                    "location": row['location'], 
                    "current_qty": int(row['quantity'])
                }
            
            selected_key = st.radio("Select the specific item/bin you are pulling from:", options=list(options.keys()), format_func=lambda x: options[x]["label"])
            chosen = options[selected_key]
            
            take_qty = st.number_input("Quantity to take:", min_value=1, max_value=chosen["current_qty"], value=1, step=1)
            
            if st.button("🔴 Confirm Items Taken"):
                if take_qty > chosen["current_qty"]:
                    st.error(f"❌ Operation blocked. Only {chosen['current_qty']} units exist.")
                else:
                    with conn.session as session:
                        if take_qty == chosen["current_qty"]:
                            session.execute(
                                text(f"DELETE FROM {TABLE_NAME} WHERE sku = :sku AND location = :loc;"), 
                                {"sku": chosen["sku"], "loc": chosen["location"]}
                            )
                            st.toast(f"✅ {chosen['sku']} at {chosen['location']} cleared from system.")
                        else:
                            new_qty = chosen["current_qty"] - take_qty
                            session.execute(
                                text(f"UPDATE {TABLE_NAME} SET quantity = :new_qty WHERE sku = :sku AND location = :loc;"),
                                {"new_qty": new_qty, "sku": chosen["sku"], "loc": chosen["location"]}
                            )
                            st.toast(f"✅ Subtracted {take_qty} units.")
                        session.commit()
                    st.rerun()
        else:
            st.error("❌ No matching SKUs found in database.")

    st.markdown("---")

    st.header("➕ Add / Replenish Stock")
    with st.form("add_item_form", clear_on_submit=True):
        raw_sku_input = st.text_input("SKU (Type freely without * or spaces):").strip()
        new_location = st.text_input("Location Code:").strip()
        add_qty = st.number_input("Quantity to Add:", min_value=1, value=1, step=1)
        submit_btn = st.form_submit_button("Save to Database")
        
        if submit_btn:
            if raw_sku_input and new_location:
                # 1. Clean down to core characters and convert to uppercase
                core_sku = clean_alphanumeric(raw_sku_input).upper()
                
                # 2. Enforce the 8-character rule (LLL + NN + NNN)
                if len(core_sku) != 8:
                    st.error(f"❌ Invalid SKU length. Core SKU must be exactly 8 characters (Letters/Numbers). You typed {len(core_sku)} characters.")
                else:
                    # 3. Reconstruct into target layout: LLL*NN NNN
                    formatted_sku = f"{core_sku[:3]}*{core_sku[3:5]} {core_sku[5:]}"
                    
                    check_query = f"SELECT quantity FROM {TABLE_NAME} WHERE sku = :sku AND location = :loc;"
                    dup_check = conn.query(check_query, params={"sku": formatted_sku, "loc": new_location}, ttl=0)
                    
                    with conn.session as session:
                        if not dup_check.empty:
                            existing_qty = int(dup_check.iloc[0]["quantity"])
                            session.execute(
                                text(f"UPDATE {TABLE_NAME} SET quantity = :qty, last_replenished = NOW() WHERE sku = :sku AND location = :loc;"),
                                {"qty": existing_qty + add_qty, "sku": formatted_sku, "loc": new_location}
                            )
                            st.success(f"✅ Topped up **{formatted_sku}** at **{new_location}**. Total: {existing_qty + add_qty}.")
                        else:
                            session.execute(
                                text(f"INSERT INTO {TABLE_NAME} (sku, location, quantity) VALUES (:sku, :loc, :qty);"),
                                {"sku": formatted_sku, "loc": new_location, "qty": add_qty}
                            )
                            st.success(f"✅ Successfully auto-formatted and saved as **{formatted_sku}** at **{new_location}**.")
                        session.commit()
            else:
                st.warning("Please fill out all fields before submitting.")

# =========================================================
# TAB 2: INVENTORY BROWSER (SEARCH & SHELF VIEW)
# =========================================================
with tab2:
    st.header("📋 Live Inventory View")
    
    search_col1, search_col2 = st.columns(2)
    with search_col1:
        browser_sku = st.text_input("Fuzzy SKU Search (Ignores format):", value="", key="browser_sku_input").strip()
    with search_col2:
        search_loc = st.text_input("Filter by Location Code:", value="", key="browser_loc").strip()
    
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
        df_display.columns = ["SKU (Formatted)", "Location / Coordinate", "Quantity On Hand", "Last Replenished"]
        if df_display["Last Replenished"].dt.tz is not None:
            df_display["Last Replenished"] = df_display["Last Replenished"].dt.tz_localize(None)
            
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        st.caption(f"Showing {len(df_display)} records matching filters.")
    else:
        st.info("No items match the current search filters.")