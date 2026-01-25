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

        # Remove espaços duplos causados por limpeza anterior
        cleaned_string = " ".join(string.split())

        for word in cleaned_string.split(splitter):
            if not word: 
                continue
                
            if out:
                out += f" {chain} "
            
            # --- CORREÇÃO PRINCIPAL ---
            # Escapa o apóstrofo (Carpenter's -> Carpenter\'s) para não quebrar a query
            word_escaped = word.replace("'", "\\'")
            
            out += f"{get_method(word)} contains '{word_escaped}'"
        return out

    def get_query(self, sm):
        out = []
        
        # Função auxiliar para limpar títulos (remove : e - que atrapalham a busca)
        def clean_title(t):
            return t.replace(":", " ").replace("-", " ").strip()

        if sm.stream_type == "series":
            seep_q = self.qgen(
                f"s{sm.se} e{sm.ep}, "  # sXX eXX
                f"s{int(sm.se)} e{int(sm.ep)}, "  # sX eX
                f"season {int(sm.se)} episode {int(sm.ep)}, "  # season X episode X
                f'"{int(sm.se)} x {int(sm.ep)}", '  # X x X
                f'"{int(sm.se)} x {sm.ep}"',  # X x XX
                chain="or",
                splitter=", ",
                method="fullText",
            )
            for title in sm.titles:
                clean_t = clean_title(title)
                if len(clean_t.split()) == 1:
                    out.append(
                        f"fullText contains '\"{clean_t}\"' and "
                        f"name contains '{clean_t.replace("'", "\\'")}' and ({seep_q})"
                    )
                else:
                    out.append(f"{self.qgen(clean_t)} and ({seep_q})")
        else:
            for title in sm.titles:
                clean_t = clean_title(title)
                # Verifica palavras chave únicas
                if len(clean_t.split()) == 1:
                    out.append(
                        f"fullText contains '\"{clean_t}\"' and "
                        f"name contains '{clean_t.replace("'", "\\'")}' and "
                        f"fullText contains '\"{sm.year}\"'"
                    )
                else:
                    # Busca padrão: Título + Ano
                    out.append(self.qgen(f"{clean_t} {sm.year}"))
        return out

    def file_list(self, file_fields):
        def callb(request_id, response, exception):
            if exception:
                print(f"Erro na busca do GDrive: {exception}")
            if response:
                output.extend(response.get("files", []))

        output = []
        if self.query:
            files = self.drive_instance.files()
            batch = self.drive_instance.new_batch_http_request()
            for q in self.query:
                # print(f"Query enviada: {q}") # Descomente para debug se precisar
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
                print(f"Erro ao executar batch: {e}")
                
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
        
        # Proteção caso self.results esteja vazio
        drive_ids = set(item["driveId"] for item in self.results if item.get("driveId"))

        if not drive_ids:
            return {}

        for drive_id in drive_ids:
            cached_drive_name = self.drive_names.contents.get(drive_id)
            if not cached_drive_name:
                self.drive_names.contents[drive_id] = None
                batch_inst = drives.get(driveId=drive_id, fields="name, id")
                batch.add(batch_inst, callback=callb)

        try:
            batch.execute()
        except Exception as e:
            print(f"Erro ao buscar nomes dos drives: {e}")
            
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
                # Fallback se não tiver checksum
                if not md5Checksum:
                    return True
                    
                uid = driveId + md5Checksum

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
        # Verifica se contents existe antes de acessar
        if not self.acc_token.contents:
             self.acc_token.contents = {}

        expires_in = self.acc_token.contents.get("expires_in")
        
        # Lógica de expiração segura
        token_expired = True
        if expires_in:
            try:
                # Se for string, tenta converter (caso venha de um json antigo)
                if isinstance(expires_in, str):
                    expires_in = datetime.fromisoformat(expires_in)
                token_expired = expires_in <= datetime.now()
            except:
                token_expired = True
        
        if token_expired:
            body = {
                "client_id": self.token["client_id"],
                "client_secret": self.token["client_secret"],
                "refresh_token": self.token["refresh_token"],
                "grant_type": "refresh_token",
            }
            api_url = "https://www.googleapis.com/oauth2/v4/token"
            try:
                oauth_resp = requests.post(api_url, json=body).json()
                
                # Se der erro de autenticação, retorna None ou lança erro
                if "error" in oauth_resp:
                    print(f"Erro ao renovar token: {oauth_resp}")
                    return None

                oauth_resp["expires_in"] = (
                    timedelta(seconds=oauth_resp["expires_in"]) + datetime.now()
                )

                self.acc_token.contents = oauth_resp
                self.acc_token.save()
            except Exception as e:
                print(f"Falha na requisição de token: {e}")
                return self.acc_token.contents.get("access_token")

        expiry = self.acc_token.contents.get("expires_in")
        acc_token = self.acc_token.contents.get("access_token")
        # print("Access token válido até", expiry)
        return acc_token
