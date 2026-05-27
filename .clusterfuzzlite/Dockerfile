FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:6bb326cd90cc82d526add050b67b92bf53f900d5f61aa9abd74cc2f04f622dc9

WORKDIR $SRC/fileyard
COPY . $SRC/fileyard
COPY .clusterfuzzlite/build.sh $SRC/build.sh
COPY .clusterfuzzlite/requirements.txt $SRC/fileyard/.clusterfuzzlite/requirements.txt
ENV PYTHONPATH=$SRC/fileyard

RUN python3 -m pip install --disable-pip-version-check --require-hashes -r $SRC/fileyard/.clusterfuzzlite/requirements.txt
