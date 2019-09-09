import io
import json
import os
import uuid
import zipfile
import time
from collections import namedtuple

try:
    from fs_gcsfs import GCSFS
except ImportError:
    GCSFS = None

import requests
from marshmallow import Schema, fields, validate


__version__ = "1.5.0"


BUCKET = os.environ.get("BUCKET", None)


class Serializer:
    def __init__(self, ext):
        self.ext = ext

    def serialize(self, data):
        return data

    def deserialize(self, data):
        return data


class JSONSerializer(Serializer):
    def serialize(self, data):
        return json.dumps(data).encode()

    def deserialize(self, data):
        return json.loads(data.decode())


class TextSerializer(Serializer):
    def serialize(self, data):
        return data.encode()

    def deserialize(self, data):
        return data.decode()


def get_serializer(media_type):
    return {
        "bokeh": JSONSerializer("json"),
        "table": TextSerializer("html"),
        "CSV": TextSerializer("csv"),
        "PNG": Serializer("png"),
        "JPEG": Serializer("jpeg"),
        "MP3": Serializer("mp3"),
        "MP4": Serializer("mp4"),
        "HDF5": Serializer("h5"),
        "PDF": Serializer("pdf"),
        "Markdown": TextSerializer("md"),
        "Text": TextSerializer("txt"),
    }[media_type]


class Output:
    """Output mixin shared among LocalOutput and RemoteOutput"""

    title = fields.Str()
    media_type = fields.Str(
        validate=validate.OneOf(choices=["bokeh", "table", "CSV", "PNG", "JPEG", "MP3", "MP4", "HDF5", "PDF", "Markdown", "Text"])
    )


class RemoteOutput(Output, Schema):
    filename = fields.Str()


class RemoteOutputCategory(Schema):
    outputs = fields.Nested(RemoteOutput, many=True)
    ziplocation = fields.Str()


class RemoteResult(Schema):
    """Serializer for load_from_S3like"""

    renderable = fields.Nested(RemoteOutputCategory, required=False)
    downloadable = fields.Nested(RemoteOutputCategory, required=False)


class LocalOutput(Output, Schema):
    # Data could be a string or dict. It depends on the media type.
    data = fields.Field()


class LocalResult(Schema):
    """Serializer for load_to_S3like"""

    renderable = fields.Nested(LocalOutput, many=True)
    downloadable = fields.Nested(LocalOutput, many=True)


def write_to_s3like(task_id, loc_result, do_upload=True):
    if GCSFS is not None:
        gcsfs = GCSFS(BUCKET)
    else:
        gcsfs = None
    s = time.time()
    LocalResult().load(loc_result)
    rem_result = {}
    for category in ["renderable", "downloadable"]:
        buff = io.BytesIO()
        zipfileobj = zipfile.ZipFile(buff, mode="w")
        ziplocation = f"{task_id}_{category}.zip"
        rem_result[category] = {"ziplocation": ziplocation, "outputs": []}
        for output in loc_result[category]:
            serializer = get_serializer(output["media_type"])
            ser = serializer.serialize(output["data"])
            filename = output["title"]
            if not filename.endswith(f".{serializer.ext}"):
                filename += f".{serializer.ext}"
            zipfileobj.writestr(filename, ser)
            rem_result[category]["outputs"].append(
                {
                    "title": output["title"],
                    "media_type": output["media_type"],
                    "filename": filename,
                }
            )
        zipfileobj.close()
        buff.seek(0)
        if do_upload:
            with gcsfs.open(ziplocation, "wb") as f:
                f.write(buff.read())
    f = time.time()
    print(f"Write finished in {f-s}s")
    return rem_result


def read_from_s3like(rem_result):
    gcsfs = GCSFS(BUCKET)
    s = time.time()
    RemoteResult().load(rem_result)
    read = {"renderable": [], "downloadable": []}
    for category in rem_result:
        with gcsfs.open(rem_result[category]["ziplocation"], "rb") as f:
            res = f.read()

        buff = io.BytesIO(res)
        zipfileobj = zipfile.ZipFile(buff)

        for rem_output in rem_result[category]["outputs"]:
            ser = get_serializer(rem_output["media_type"])
            rem_data = ser.deserialize(zipfileobj.read(rem_output["filename"]))
            read[category].append(
                {
                    "title": rem_output["title"],
                    "media_type": rem_output["media_type"],
                    "data": rem_data,
                }
            )
    f = time.time()
    print(f"Read finished in {f-s}s")
    return read
