FROM gcr.io/oss-fuzz-base/base-builder-python

WORKDIR $SRC/movi-organizer
COPY . $SRC/movi-organizer
COPY .clusterfuzzlite/build.sh $SRC/build.sh

RUN python3 -m pip install --disable-pip-version-check --upgrade pip==26.0.1 \
    && python3 -m pip install --disable-pip-version-check atheris \
    && python3 -m pip install --disable-pip-version-check .
