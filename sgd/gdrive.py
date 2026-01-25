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

        # --- CORREÇÃO SEGURA ---
        # 1. Troca pontos por espaços (para achar releases scene The.Movie...)
        # 2. Remove apóstrofos (Carpenter's -> Carpenters) para não quebrar a sintaxe
        cleaned_string = string.replace(".", " ").replace("'", "")
        
        # Remove espaços duplos
        cleaned_string = " ".join(cleaned_string.split())

        for word in cleaned_string.split(splitter):
            if not word: continue
            
            if out:
                out += f" {chain} "
            # Busca simples e original que funcionava
            out += f"{get_method(word)} contains '{word}'"
        return out

    def get_query(self, sm):
        out = []

        if sm.stream_type == "series":
            # Adicionei SxxExx junto, pois muitos arquivos usam esse formato
            se = str(sm.se).zfill(2)
            ep = str(sm.ep).zfill(2)
            
            seep_q = self.qgen(
                f"S{sm.se}E{sm.ep}, " # Formato S01E01 junto (importante)
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
                # Remove apóstrofos do título antes de mandar buscar
                clean_t = title.replace("'", "")
                
                if len(clean_t.split()) == 1:
                    out.append(
                        f"fullText contains '\"{clean_t}\"' and "
                        f"name contains '{clean_t}' and ({seep_q})"
                    )
                else:
                    out.append(f"{self.qgen(clean_t)} and ({seep_q})")
        else:
            for title in sm.titles:
                # Remove apóstrofos do título
                clean_t = title.replace("'", "")
                
                if len(clean_t.split()) == 1:
                    out.append(
                        f"fullText contains '\"{clean_t}\"' and "
                        f"name contains '{clean_t}'"
                    )
                else:
                    # Removi a obrigatoriedade do ANO aqui. 
                    # Deixa o Python filtrar o ano depois, para achar 2024/2025.
                    out.append(self.qgen(f"{clean_t}"))
        return out

    def file_list(self, file_fields):
        def callb(request_id, response, exception):
            if response:
                output.extend(response.get("files", []))
            # Se der erro, apenas ignora e segue (evita crash)
            if exception:
                print(f"Aviso GDrive: {exception}")

        output = []
        if self.query:
            files = self.drive_instance.files()
            batch = self.drive_instance.new_batch_http_request()
            for q in self.query:
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
            except:
                pass # Se falhar a conexão, não quebra o addon
            return output
        return output

    def get_drive_names(self):
        def callb(request_id, response, exception):
            if response:
                drive_id = response.get("id")
                drive_name = response.get("name")
                self.drive_names.contents[drive_id] = drive_name

        batch = self.drive_instance.new_batch_http_request()
        drives = self.drive_instance.drives()
        
        drive_ids = set(item.get("driveId") for item in self.results if item.get("driveId"))
        
        if not drive_ids: return {}

        for drive_id in drive_ids:
            cached_drive_name = self.drive_names.contents.get(drive_id)
            if not cached_drive_name:
                self.drive_names.contents[drive_id] = None
                batch_inst = drives.get(driveId=drive_id, fields="name, id")
                batch.add(batch_inst, callback=callb)

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
                # Se não tiver checksum, usa o ID
                uid = driveId + (md5Checksum if md5Checksum else item.get("id"))

                if uid in uids:
                    return False

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
        
        # Lógica de expiração segura
        is_expired = True
        expires = self.acc_token.contents.get("expires_in")
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
                    oauth_resp["expires_in"] = (
                        timedelta(seconds=oauth_resp["expires_in"]) + datetime.now()
                    )
                    self.acc_token.contents = oauth_resp
                    self.acc_token.save()
            except: pass

        return self.acc_token.contents.get("access_token")
