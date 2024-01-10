from flask import Flask, render_template, request, jsonify
from imdb import IMDb

app = Flask(__name__)
cinema_goer = IMDb()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search_movies')
def search_movies():
    keyword = request.args.get('keyword')

    try:
        movies = cinema_goer.search_movie(keyword)
        movie_data = []

        for movie in movies[:10]:  # Limit to the first 10 results for simplicity
            # Use larger images for better quality
            cover_url = movie.get('cover url', '')
            if cover_url:
                cover_url = cover_url.replace('._V1_SX300', '._V1_SX600')  # Increase the size
            movie_data.append({
                'imdb_id': movie.movieID,
                'title': movie['title'],
                'year': movie.get('year', ''),
                'thumbnail': cover_url,
            })

        return jsonify(movie_data)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/get_movie_details')
def get_movie_details():
    imdb_id = request.args.get('imdbId')

    try:
        movie = cinema_goer.get_movie(imdb_id)
        details = {
            'title': movie['title'],
            'year': movie.get('year', ''),
            'genres': movie.get('genres', []),
            'directors': [director['name'] for director in movie.get('directors', [])]
        }

        return jsonify(details)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/watch')
def watch_movie():
    imdb_id = request.args.get('imdbId')
    return render_template('watch.html', imdb_id=imdb_id)

if __name__ == "__main__":
    app.run(debug=True)
