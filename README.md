# bandcamp-profile

## Description 

Get Bandcamp profile information (owned tracks, wishlist, ...)

## Usage

List arguments, example usage
```bash
python3 main.py -h
```

Get profile information
```bash
username=lmnd
python3 main.py https://bandcamp.com/$username
```

Download all albums (using jq and [bandcamp-dl](https://github.com/iheanyi/bandcamp-dl))
```bash
username=lmnd
output_dir=bandcamp/
python3 main.py https://bandcamp.com/$username | jq -r ".items.[].url" | xargs -n1 bandcamp-dl --base-dir=$output_dir
```
