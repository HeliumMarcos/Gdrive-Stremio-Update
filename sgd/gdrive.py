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

        # --- CORREÇÃO DE SEGURANÇA ---
        # Remove caracteres que quebram a busca (apóstrofos, dois pontos, traços)
        # Ex: "Carpenter's" vira "Carpenters" (O Google entende e não dá erro)
        cleaned_string = string.replace("'", "").replace(":", " ").replace("-", " ")
        cleaned_string = " ".join(cleaned_string.split()) # Remove espaços duplos

        for word in cleaned_string.split(splitter):
            if not word: continue
            if out: out += f" {chain} "
            out += f"{get_method(word)} contains '{word}'"
        return out

    def get_query(self, sm):
        out = []
        
        # Função para limpar o título base
        def clean_title(t):
            # Remove apóstrofos e caracteres especiais do título original
            return t.replace("'", "").replace(":", " ").replace("-", " ").strip()

        if sm.stream_type == "series":
            # Gera variações de temporada/episódio
            se = str(sm.se).zfill(2)
            ep = str(sm.ep).zfill(2)
            
            seep_q = self.qgen(
                f"S{se}E{ep}, "       # S01E01 (Formato do seu arquivo The.Pitt)
                f"S{se} E{ep}, "      # S01 E01
                f"s{se} e{ep}, "      # s01 e01
                f"{int(se)}x{ep}, "   # 1x01
                f"{se}.{ep}",         # 01.01
                chain="or",
                splitter=", ",
                method="name",
            )
            
            for title in sm.titles:
                clean_t = clean_title(title)
                # Busca: Nome Limpo E (Alguma variação de episódio)
                out.append(f"({self.qgen(clean_t)}) and ({seep_q})")
                
        else:
            # FILMES
            for title in sm.titles:
                clean_t = clean_title(title)
                # Busca ampla: Pelo nome limpo (sem ano, para achar 2025/2024)
                # E também busca com ano para garantir prioridade se existir
                out.append(f"{self.qgen(clean_t)}")
                
        return out

    def file_list(self, file_fields):
        def callb(request_id, response, exception):
            if exception:
                print(f"Erro na busca GDrive: {exception}")
            if response:
                output.extend(response.get("files", []))

        output = []
        if self.query:
            files = self.drive_instance.files()
            batch = self.drive_instance.new_batch_http_request()
            for q in self.query:
                # print(f"Query enviada: {q}") # Debug
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
                print(f"Erro fatal no Batch: {e}")
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
                batch.add(drives.get(driveId=drive_id, fields="name, id"), callback=callb)

        try:
            batch.execute()
        except:
            pass
            
        self.drive_names.save()
        return self.drive_names.contents

    def search(self, stream_meta):
        self.results = []
        self.query = self.get_query(stream_meta)

        response = self.file_list("id, name, size, driveId, md5Checksum, createdTime")
        
        if response:
            uids = set()
            def check_dupe(item):
                uid = item.get("driveId", "MyD") + item.get("md5Checksum", item.get("id"))
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
            try:
                body = {
                    "client_id": self.token["client_id"],
                    "client_secret": self.token["client_secret"],
                    "refresh_token": self.token["refresh_token"],
                    "grant_type": "refresh_token",
                }
                res = requests.post("https://www.googleapis.com/oauth2/v4/token", json=body).json()
                
                if "access_token" in res:
                    res["expires_in"] = timedelta(seconds=res["expires_in"]) + datetime.now()
                    self.acc_token.contents = res
                    self.acc_token.save()
            except:
                pass

        return self.acc_token.contents.get("access_token")
