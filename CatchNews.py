import os
import firebase_admin
from firebase_admin import credentials, firestore

# 初始化 Firebase
cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
firebase_admin.initialize_app(cred)
db = firestore.client()

# 指定要刪除的 document
doc_id = "20251208"
ref = db.collection("NEWS_LiteOn").document(doc_id)

# 刪除整個 document
ref.delete()

print(f"✅ 已刪除 Firestore：NEWS_LiteOn/{doc_id}")
