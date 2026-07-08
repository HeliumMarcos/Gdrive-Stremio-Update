from sgd import app, gdrive
from sgd.meta import MetadataNotFound, Meta
from sgd.streams import Streams
from json import dumps
from flask import jsonify, abort, Response
from datetime import datetime


MANIFEST = {
    "id": "streamhelium.stremio.googledrive",
    "version": "1.1.3",
    "name": "Stream Helium",
    "description": "Este plugin busca Filmes e Séries.",
"favicon": "https://heliummarcos.com.br/addons/meu-addon/favicon.png",
    "logo": "https://heliummarcos.com.br/addons/meu-addon/gdrive.png",
    "background": "https://heliummarcos.com.br/addons/meu-addon/background.png",
    "resources": ["stream"],
    "types": ["movie", "series"],
    "catalogs": [],
}


@app.route("/")
def init():
    return "O addon está ativo."


@app.route("/favicon.png")
def favicon():
    return "", 204


@app.route("/manifest.json")
def addon_manifest():
    return common_headers(jsonify(MANIFEST))


@app.route("/stream/<stream_type>/<stream_id>.json")
def addon_stream(stream_type, stream_id):

    invalid_stream_type = stream_type not in MANIFEST["types"]

    # Aceita IDs que começam com "tt" (IMDB) ou "tmdb" (TMDB)
    base_id = stream_id.split("%3A")[0].lower()
    invalid_id = base_id[:2] != "tt" and base_id != "tmdb"

    if invalid_stream_type or invalid_id:
        abort(404)
    try:
        resp = Response(
            response=get_streams(stream_type, stream_id),
            mimetype="application/json",
        )
        return common_headers(resp)
    except MetadataNotFound as e:
        print(f"ERROR: {e}")
        abort(404)


def common_headers(resp_obj):
    resp_obj.headers["Access-Control-Allow-Origin"] = "*"
    resp_obj.headers["Access-Control-Allow-Headers"] = "*"
    resp_obj.headers["X-Robots-Tag"] = "noindex"
    return resp_obj


def get_streams(stream_type, stream_id):
    # Janky way to extend 30 second timeout:
    # https://devcenter.heroku.com/articles/request-timeout#long-polling-and-streaming-responses
    yield '{"streams":'

    start_time = datetime.now()
    time_taken = lambda st: f"{(datetime.now() - st).total_seconds():.3f}s"

    stream_meta = Meta(stream_type, stream_id)
    gdrive.search(stream_meta)
    print(
        f"Got {len(gdrive.results)}/{gdrive.len_response} unique "
        f"results from gdrive after deduping in {time_taken(start_time)}."
        " Processando resultados..."
    )
    streams = Streams(gdrive, stream_meta)
    print(
        f"Fetched {len(streams.results)}/{len(gdrive.results)} "
        f"valid stream(s) in {time_taken(start_time)} for "
        f"{stream_id} -> {gdrive.query}"
    )

    yield f"{dumps(streams.results)}}}"
