import re
import logging
from sgd import app, gdrive
from sgd.meta import MetadataNotFound, Meta
from sgd.streams import Streams
from sgd.utils import split_stream_id
from json import dumps
from flask import jsonify, abort, Response, redirect
from datetime import datetime

logger = logging.getLogger(__name__)

# tt1234567 for IMDb ids, or tmdb:1234 for TMDB ids, optionally followed by
# :<season>:<episode> for series.
VALID_IMDB_ID = re.compile(r"^tt\d{5,10}$", re.IGNORECASE)
VALID_SEASON_EPISODE = re.compile(r"^\d+$")


def is_valid_stream_id(stream_id):
    parts = split_stream_id(stream_id)
    base_id = parts[0].lower()

    if base_id == "tmdb":
        if len(parts) < 2 or not parts[1].isdigit():
            return False
        extra = parts[2:]
    elif VALID_IMDB_ID.match(base_id):
        extra = parts[1:]
    else:
        return False

    return len(extra) <= 2 and all(VALID_SEASON_EPISODE.match(p) for p in extra)


MANIFEST = {
    "id": "streamhelium.stremio.googledrive",
    "version": "1.1.4",
    "name": "Stream Helium",
    "description": "Este plugin busca Filmes e Séries.",
"favicon": "https://catalogo.heliummarcos.com.br/addon/favicon.png",
    "logo": "https://catalogo.heliummarcos.com.br/addon/gdrive.png",
    "background": "https://catalogo.heliummarcos.com.br/addon/background.png",
    "resources": ["stream"],
    "types": ["movie", "series"],
    "catalogs": [],
}


@app.route("/")
def init():
    return "O addon está ativo."


@app.route("/favicon.png")
@app.route("/favicon.ico")
def favicon():
    return redirect(MANIFEST["favicon"], code=302)


@app.route("/manifest.json")
def addon_manifest():
    return common_headers(jsonify(MANIFEST))


@app.route("/stream/<stream_type>/<stream_id>.json")
def addon_stream(stream_type, stream_id):

    invalid_stream_type = stream_type not in MANIFEST["types"]
    invalid_id = not is_valid_stream_id(stream_id)

    if invalid_stream_type or invalid_id:
        abort(404)
    try:
        resp = Response(
            response=get_streams(stream_type, stream_id),
            mimetype="application/json",
        )
        return common_headers(resp)
    except MetadataNotFound as e:
        logger.info("%s", e)
        abort(404)


def common_headers(resp_obj):
    resp_obj.headers["Access-Control-Allow-Origin"] = "*"
    resp_obj.headers["Access-Control-Allow-Headers"] = "*"
    resp_obj.headers["X-Robots-Tag"] = "noindex"
    return resp_obj


def get_streams(stream_type, stream_id):
    # Stream the response body so the connection stays open (and doesn't hit
    # a request timeout) while we search Drive and score the results.
    yield '{"streams":'

    start_time = datetime.now()
    time_taken = lambda st: f"{(datetime.now() - st).total_seconds():.3f}s"

    stream_meta = Meta(stream_type, stream_id)
    gdrive.search(stream_meta)
    logger.info(
        "Got %d/%d unique results from gdrive after deduping in %s. Scoring results...",
        len(gdrive.results), gdrive.len_response, time_taken(start_time),
    )
    streams = Streams(gdrive, stream_meta)
    logger.info(
        "Fetched %d/%d valid stream(s) in %s for %s -> %s",
        len(streams.results), len(gdrive.results), time_taken(start_time),
        stream_id, gdrive.query,
    )

    yield f"{dumps(streams.results)}}}"
