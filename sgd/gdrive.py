import requests
from datetime import datetime, timedelta
from sgd.cache import Pickle, Json
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


class GoogleDrive:
    def __init__(self, token):
        self.token = token
        self.page_size = 1000
        self.acc_token = Pickle("acctoken.pickle")
        self.drive_names = Json("drivenames.json")

        creds = Credentials.from_authorized_user_info(self.token)
        self.drive_instance = build("drive", "v3", credentials=creds)

    @staticmethod
    def qgen(string, chain="and", splitter=" ", method=None):
        out = ""

        get_method = lambda _: method
        if not method:
            get_method = lambda w: "fullText" if w.isdigit() else "name"

        # --- LISTA DE PALAVRAS COMUNS (STOP WORDS) ---
        STOP_WORDS = {
            "the", "of", "and", "a", "an", "to", "in", "for", "on", "at", 
            "by", "with", "from", "as", "is", "it"
        }

        # 1. Limpeza básica: remove pontuação e apóstrofos
        # "The Carpenter's Son" -> "The Carpenter s Son"
        # "The Rip" -> "The Rip"
        cleaned_string = string.replace(".", " ").replace("'", " ").replace(":", " ").replace("-", " ")
        cleaned_string = " ".join(cleaned_string.split())

        all_words = []
        # Filtra palavras inúteis menores que 2 letras (mas mantém números)
        for w in cleaned_string.split(splitter):
            if w and (len(w) > 1 or w.isdigit()):
                all_words.append(w)

        # 2. Identifica palavras "Fortes" (que não são Stop Words)
        strong_words = [w for w in all_words if w.lower() not in STOP_WORDS]

        # --- LÓGICA INTELIGENTE (AQUI ESTÁ A MÁGICA) ---
        # Se o título tiver POUCAS palavras fortes (1 ou menos), precisamos das Stop Words!
        # Exemplo: "The Rip" -> Strong: ["Rip"]. Count: 1. -> Mantém "The" e "Rip".
        # Exemplo: "The Carpenter's Son" -> Strong: ["Carpenter", "Son"]. Count: 2. -> Remove "The".
        
        if len(strong_words) <= 1:
            # Título curto/genérico: Usa TUDO para ser específico (ex: "The Rip")
            final_words = all_words
        else:
            # Título longo: Usa só as fortes para garantir match (ex: "Carpenter Son")
            final_words = strong_words

        # Se por acaso a lista ficar vazia (ex: filme chamado "The"), usa o original
        if not final_words:
            final_words = all_words

        for word in final_words:
            if out:
                out += f" {chain} "
            out += f"{get_method(word)} contains '{word}'"
            
        return out

    def get_query(self, sm):
        out = []
        
        # DEBUG
        print(f"--- DEBUG ---")
        print(f"TITULO: {sm.titles}")

        if sm.stream_type == "series":
            # Busca de Séries
            se = str(sm.se).zfill(2)
            ep = str(sm.ep).zfill(2)
            
            seep_q = self.qgen(
                f"S{sm.se}E{sm.ep}, "
                f"s{sm.se} e{sm.ep}, "
                f"s{int(sm.se)} e{int(sm.ep)}, "
                f"season {int(sm.se)} episode {int(sm.ep)}, "
                f'"{int(sm.se)} x {int(sm.ep)}", '
                f'"{int(sm.se)} x {sm.ep}"',
                chain="or",
                splitter=", ",
                method="fullText",
            )
            for title in sm.titles:
                query_part = self.qgen(title)
                if not query_part: continue

                if len(title.split()) == 1:
                    clean_t = title.replace("'", " ")
                    out.append(
                        f"fullText contains '\"{clean_t}\"' and "
                        f"name contains '{clean_t}' and ({seep_q})"
                    )
                else:
                    out.append(f"{query_part} and ({seep_q})")
        else:
            # Busca de Filmes
            for title in sm.titles:
                q = self.qgen(title)
                if q:
                    out.append(q)
        
        return out

    def file_list(self, file_fields):
        def callb(request_id, response, exception):
            if response:
                output.extend(response.get("files", []))
            if exception:
                print(f"Erro GDrive: {exception}")

        output = []
        if self.query:
            files = self.drive_instance.files()
            batch = self.drive_instance.new_batch_http_request()
            
            for q in self.query:
                # O log vai te mostrar a diferença agora
                print(f"BUSCA SMART: {q}") 
                
                batch_inst = files.list(
                    q=f"{q} and trashed=false and mimeType contains 'video/'",
                    fields=f"files({file_fields})",
                    pageSize=self.page_size,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
                )
                batch.add(batch_inst, callback=callb)
            try:
                batch.execute()
            except Exception as e:
                print(f"Erro Batch: {e}")
                
            return output
        return output

    def get_drive_names(self):
        def callb(request_id, response, exception):
            if response:
                self.drive_names.contents[response.get("id")] = response.get("name")

        batch = self.drive_instance.new_batch_http_request()
        drives = self.drive_instance.drives()
        
        drive_ids = set(item.get("driveId") for item in self.results if item.get("driveId"))
        
        if not drive_ids: return {}

        for drive_id in drive_ids:
            if not self.drive_names.contents.get(drive_id):
                self.drive_names.contents[drive_id] = None
                batch_inst = drives.get(driveId=drive_id, fields="name, id"), callback=callb)

        try:
            batch.execute()
        except: pass
            
        self.drive_names.save()
        return self.drive_names.contents

    def search(self, stream_meta):
        self.results = []
        self.query = self.get_query(stream_meta)

        response = self.file_list("id, name, size, driveId, md5Checksum")
        self.len_response = 0

        if response:
            self.len_response = len(response)
            uids = set()

            def check_dupe(item):
                driveId = item.get("driveId", "MyDrive")
                md5Checksum = item.get("md5Checksum")
                uid = driveId + (md5Checksum if md5Checksum else item.get("id"))

                if uid in uids: return False
                uids.add(uid)
                return True

            self.results = sorted(
                filter(check_dupe, response),
                key=lambda item: int(item.get("size", 0)),
                reverse=True,
            )

        self.get_drive_names()
        return self.results

    def get_acc_token(self):
        if not self.acc_token.contents: self.acc_token.contents = {}
        expires = self.acc_token.contents.get("expires_in")
        is_expired = True
        
        if expires:
            try:
                if isinstance(expires, str): expires = datetime.fromisoformat(expires)
                is_expired = expires <= datetime.now()
            except: pass

        if is_expired:
            body = {
                "client_id": self.token["client_id"],
                "client_secret": self.token["client_secret"],
                "refresh_token": self.token["refresh_token"],
                "grant_type": "refresh_token",
            }
            api_url = "https://www.googleapis.com/oauth2/v4/token"
            try:
                oauth_resp = requests.post(api_url, json=body).json()
                if "access_token" in oauth_resp:
                    oauth_resp["expires_in"] = timedelta(seconds=oauth_resp["expires_in"]) + datetime.now()
                    self.acc_token.contents = oauth_resp
                    self.acc_token.save()
            except: pass

        return self.acc_token.contents.get("access_token")
