from app.domain.weather_types import PressureLevelData, WeatherData


def test_weather_data_accepts_pressure_levels() -> None:
    level = PressureLevelData(
        pressure_hpa=925,
        altitude_m=800,
        temperature_c=4.0,
        relative_humidity=91.0,
        dew_point_spread=1.2,
    )
    weather = WeatherData(
        cloud_base=900,
        humidity=88.0,
        wind_speed=12.0,
        temperature_2m=7.0,
        temperature_850hpa=6.0,
        temperature_925hpa=3.0,
        pressure=1021.0,
        cloud_cover_low=70.0,
        month=3,
        pressure_levels=[level],
    )

    assert weather.pressure_levels == [level]
    assert weather.cloud_cover_low == 70.0
