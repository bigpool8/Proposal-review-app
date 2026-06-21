import axios from "axios";
import toast from "react-hot-toast";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
});

api.interceptors.request.use((config) => {
  const token =
    typeof window !== "undefined"
      ? localStorage.getItem("access_token")
      : null;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (typeof window === "undefined") return Promise.reject(error);

    if (error.response?.status === 401) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("username");
      window.location.href = "/login";
    } else if (error.response) {
      const detail: string =
        error.response.data?.detail || "오류가 발생했습니다.";
      toast.error(detail);
    }
    return Promise.reject(error);
  }
);

export default api;
