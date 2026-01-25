import requests
import re
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

        # --- CORREÇÃO DEFINITIVA ---
        # Extrai APENAS letras e números. Ignora ' : - . e tudo mais.
        # Ex: "The Carpenter's Son" vira ["The", "Carpenter", "s", "Son"]
        words = re.findall(r'\w+', string)
        
        # Filtra palavras inúteis (uma letra só, ou artigos comuns que sujam a busca)
        valid_words = [w for w in words if len(w) > 1 and w.lower() not in ('the', 'and', 'of')]
        
        if not valid_words: # Se não sobrou nada, usa o original
            valid_words = words

        for word in valid_words:
            if out: out += f" {chain} "
            out += f"{get_method(word)} contains '{word}'"
            
        return out

    def get_query(self, sm):
        out = []
        
        # Pega o título principal (sem apóstrofos ou caracteres estranhos)
        for title in sm.titles:
            # Busca Série
            if sm.stream_type == "series":
                se = str(sm.se).zfill(2) # 01
                ep = str(sm.ep).zfill(2) # 04
                se_int = int(sm.se)      # 1
                ep_int = int(sm.ep)      # 4

                # Variações de busca S01E01
                episode_queries = [
                    f"S{se}E{ep}",       # S01E01 (Padrão scene)
                    f"S{se} E{ep}",      # S01 E01
                    f"{se_int}x{ep_int}",# 1x4
                    f"{se}.{ep}"         # 01.04
                ]
                
                # Gera a query para cada variação de episódio
                ep_string = ""
                for i, eq in enumerate(episode_queries):
                    prefix = " or " if i > 0 else ""
                    ep_string += f"{prefix}name contains '{eq}'"

                # Query Final: (NomeLimpo) AND (VariaçõesEpisodio)
                title_query = self.qgen(title)
                if title_query:
                    out.append(f"({title_query}) and ({ep_string})")

            # Busca Filme
            else:
                # Busca apenas pelo NOME. 
                # Removemos o ANO da busca do Google para evitar falhas se o ano estiver errado.
                q = self.qgen(title)
                if q:
                    out.append(q)
                
        return out

    def file_list(self, file_fields):
        def callb(request_id, response, exception):
            if exception:
                print(f"Erro GDrive: {exception}")
            if response:
                output.extend(response.get("files", []))

        output = []
        if self.query:
            files = self.drive_instance.files()
            batch = self.drive_instance.new_batch_http_request()
            for q in self.query:
                # print(f"Query: {q}") # Debug
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
                batch.add(drives.get(driveId=drive_id, fields="name, id"), callback=callb)

        try:
            batch.execute()
        except: pass
            
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
            except: pass

        return self.acc_token.contents.get("access_token")
