# 🛍️ Saira AI Agent: AI-Powered E-Commerce Analytics & Conversational Agent System

[![Course](https://img.shields.io/badge/Course-Artificial%20Intelligence-blue.svg)]()
[![Institution](https://img.shields.io/badge/FAST--NUCES-Lahore-red.svg)]()
[![Status](https://img.shields.io/badge/Status-Phase%203%20Completed-success.svg)]()

An intelligent conversational agent and analytics backend designed for social commerce retailers (*Saira Fashion House*). The system automates customer interactions over WhatsApp and Instagram, handling bilingual Roman Urdu/English queries, real-time stock checks, order tracking, exchanges, and intelligent escalation handoffs.

---

## 👥 Team Members (Group F26-07)
* **Eman Fatima** (24L-3008) — *Software Engineering Student*
* **Rabia** (24L-3093)
* **Abdullah Tahir** (24L-3061)
* **Shahzaib Zia** (24L-3057)

---

## 🚀 Project Overview & Phases

### **Phase 1: Data Collection & Curation**
* Designed and curated specialized datasets tailored for social media fashion retail in Pakistan.
* Collected structured product catalogs (`catalog.csv`), transaction order histories (`orders.csv`), company policies (`policy.md`), and bilingual customer conversation logs (`conversations.json`).

### **Phase 2: Preprocessing, Quality Checks & EDA**
* **Data Cleansing:** Standardized SKU variants, cleaned pricing/sale logic, and normalized text casing.
* **Exploratory Data Analysis (EDA):** Analyzed code-mixing distributions (revealing that 94% of conversations mix Roman Urdu and English), customer intent frequencies (Stock checks, Orders, Exchanges), and escalation triggers.
* **RAG Chunking:** Split policy guidelines into optimized retrieval chunks (`policy_chunks.json`).

### **Phase 3: Model Building, Agent Pipeline & Evaluation**
* **Text Prenormalization Engine:** Sanitizes emojis, extra whitespace, and standardizes local phone numbers (`0300-1234567` $\rightarrow$ `03001234567`).
* **Intent Classifier & Escalation Guardrail:** Maps user messages to core intents (`check_stock`, `place_order`, `order_status`, `exchange`, `recommend`, `policy_question`) while intercepting critical escalation triggers (refund demands, abusive language, high COD thresholds > Rs. 25,000, and human agent requests).
* **RAG Policy Retriever:** Connects customer questions to company policy guidelines without hallucination.
* **Evaluation:** Achieved **94.2% intent classification accuracy** and **96.5% escalation precision** across the held-out test split.

---

## 📂 Repository Structure

```text
├── catalog_clean.csv          # Cleaned product variant catalog
├── orders_clean.csv           # Cleaned transaction order history
├── policy_chunks.json         # Chunked company policies for RAG retrieval
├── conversations_clean.json   # Curated bilingual conversation dataset (Dev & Test splits)
├── agent_pipeline.py          # Core Python module for intent detection & agent pipeline
├── F26-07.ipynb               # Phases 1 & 2 Jupyter Notebook (EDA & Data Preprocessing)
├── F26-07_Phase3.ipynb        # Phase 3 Jupyter Notebook (Model Building & Evaluation)
└── Phase3_Model_Building_Report.docx  # Detailed Phase 3 Technical & Evaluation Report
